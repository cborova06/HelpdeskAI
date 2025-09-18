# -*- coding: utf-8 -*-
# TR: HelpdeskAI lisans akışları: activate / deactivate / verify / gatekeeper (+30g grace)
from __future__ import annotations
import json, uuid, time
from typing import Dict, Any, Tuple
from urllib.parse import urlparse
import requests
from requests.exceptions import RequestException, Timeout
import frappe
from frappe.utils import now_datetime, get_datetime, add_days, cint

# TR: Uç noktalar sabit (Settings'ten değiştirilemez)
DEFAULT_ACTIVATE_URL   = "https://brvsoftware.com/wp-json/brv-slm/v1/activate-license"
DEFAULT_DEACTIVATE_URL = "https://brvsoftware.com/wp-json/brv-slm/v1/deactivate-license"
DEFAULT_VERIFY_URL     = "https://brvsoftware.com/wp-json/brv-slm/v1/verify-license"

# TR: Cache anahtarları
CACHE_STATUS_KEY = "helpdesk:license:status"          # 'valid' | 'grace' | 'invalid' | 'unknown'
CACHE_LAST_CHECK = "helpdesk:license:last_check_ts"   # epoch ts

# TR: Kurumsal tolerans (gün)
BILLING_GRACE_DAYS = 30

# ---------------------------------------------------------------------------

# TR: Settings dokümanı

def _settings():
    return frappe.get_single("HelpdeskAI Settings")

# TR: Domain doğrulama (yalnız brvsoftware.com)

def _assert_brv_domain(url: str):
    netloc = urlparse(url).netloc.lower()
    if netloc != "brvsoftware.com":
        raise frappe.PermissionError(f"Beklenen domain brvsoftware.com; görülen: {netloc}")

def _iso(dt) -> str | None:
    # TR: Ne gelirse gelsin güvenle ISO string'e çevir
    if not dt:
        return None
    try:
        # dt string de olsa datetime de olsa normalize et
        return get_datetime(dt).isoformat()
    except Exception:
        try:
            return dt.isoformat()  # TR: zaten datetime ise
        except Exception:
            return str(dt)         # TR: son çare



def _get_product_id() -> str:
    """TR: HelpdeskAI Settings içinden Product ID'yi zorunlu olarak alır."""
    st = _settings()
    pid = (getattr(st, "product_id", "") or "").strip()
    if not pid:
        frappe.throw("Product ID gerekli. Lütfen HelpdeskAI Settings üzerinde doldurun.")
    return pid

# TR: instance_id üretimi (ilk çağrıda otomatik)

def _ensure_instance_id() -> str:
    st = _settings()
    if not getattr(st, "instance_id", None):
        st.instance_id = str(uuid.uuid4())
        st.save(ignore_permissions=True)
        frappe.db.commit()
    return st.instance_id

# TR: HTTP POST (Bearer + domain teyidi)

def _post(url: str, license_key: str, payload: Dict[str, Any], timeout=15) -> requests.Response:
    _assert_brv_domain(url)
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {license_key}"}
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=timeout, allow_redirects=True)
    final_netloc = urlparse(resp.url).netloc.lower()
    if final_netloc != "brvsoftware.com":
        raise frappe.PermissionError(f"Yanıt domain’i beklenen değil: {final_netloc}")
    return resp

# TR: License Audit Log yazımı (özet + maskeleme)

def _write_audit(action: str, status: str, source: str, license_key: str, extra: Dict[str, Any] | None = None):
    masked = f"****-****-****-{license_key[-4:]}" if license_key else ""
    doc = frappe.new_doc("License Audit Log")
    doc.subject = f"{action} → {status}"
    doc.action = action
    st_upper = (status or "").upper()
    if st_upper in ("OK", "SUCCESS", "VALID", "ACTIVE"):
        doc.status = "OK"
    elif st_upper in ("WARN", "GRACE", "GRACE_OK"):
        doc.status = "WARN"
    else:
        doc.status = "FAIL"
    doc.source = source
    doc.event_ts = now_datetime()
    doc.user = frappe.session.user if frappe.session else None
    doc.ip_address = getattr(frappe.local, "request_ip", None)
    doc.license_key_mask = masked
    st = _settings()
    doc.instance_id = getattr(st, "instance_id", "")
    doc.app_version = frappe.utils.get_full_version() if hasattr(frappe.utils, "get_full_version") else ""
    if extra:
        doc.notes = json.dumps(extra, ensure_ascii=False)[:1400]
    try:
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()

# ---- Grace hesaplama --------------------------------------------------------

def _extract_expiry(payload: Dict[str, Any]) -> Any:
    for k in ("expires_at", "expiry", "expiresOn", "valid_till"):
        if payload.get(k):
            return payload.get(k)
    return None


def _grace_window(expires_at_dt):
    if not expires_at_dt:
        return (False, None)
    exp_dt = get_datetime(expires_at_dt)
    st = _settings()
    # TR: İlk GRACE anında kilitlenen değer/son tarih varsa onu kullan
    if cint(getattr(st, "grace_locked_days", 0)) > 0 and getattr(st, "grace_until", None):
        grace_until = get_datetime(st.grace_until)
        return (now_datetime() <= grace_until, grace_until)
    # TR: Aksi halde anlık değeri (0..30 clamp) kullan
    grace_days = cint(getattr(st, "billing_grace_days", None) or BILLING_GRACE_DAYS)
    grace_until = get_datetime(add_days(exp_dt, grace_days))
    return (now_datetime() <= grace_until, grace_until)



def _is_revoked(payload: Dict[str, Any]) -> bool:
    val = (payload.get("status") or payload.get("license_status") or "").lower()
    return any(s in val for s in ("revoked", "blacklist", "blocked"))

# ---- Public API -------------------------------------------------------------

@frappe.whitelist(methods=["POST"])
def activate(license_key: str | None = None) -> Dict[str, Any]:
    st = _settings()
    key = (license_key or getattr(st, "license_key", "") or "").strip()
    if not key:
        frappe.throw("Lisans anahtarı gerekli.")
    _ensure_instance_id(); st.reload()
    iid = st.instance_id
    pid = _get_product_id() 
    url = DEFAULT_ACTIVATE_URL
    try:
        payload = {"license_key": key, "instance_id": iid, "product_id": pid}
        resp = _post(url, key, payload)
        data = resp.json() if resp.content else {}
        ok = resp.ok and (
            data.get("status") in ("activated", "already_activated") or
            (data.get("success") is True and data.get("license_status") in ("active", "activated"))
        )
        if ok:
            exp = _extract_expiry(data)
            if exp:
                st.expires_at = get_datetime(exp)
            st.last_check_on = now_datetime(); st.last_check_status = "VALID"
            st.save(ignore_permissions=True); frappe.db.commit()
            frappe.cache().set_value(CACHE_STATUS_KEY, "valid")
            frappe.cache().set_value(CACHE_LAST_CHECK, int(time.time()))
            _write_audit("Activate", "OK", "Server", key, {"http": resp.status_code, "raw": data})
            return {"ok": True, "status": "activated", "data": data}
        else:
            st.last_check_on = now_datetime(); st.last_check_status = "INVALID"
            st.save(ignore_permissions=True); frappe.db.commit()
            frappe.cache().set_value(CACHE_STATUS_KEY, "invalid")
            _write_audit("Activate", "FAIL", "Server", key, {"http": resp.status_code, "raw": data})
            return {"ok": False, "status": "invalid", "data": data}
    except (RequestException, Timeout) as e:
        st.last_check_on = now_datetime(); st.last_check_status = "NETWORK_ERROR"
        st.save(ignore_permissions=True); frappe.db.commit()
        _write_audit("Activate", "FAIL", "Server", key, {"err": str(e)})
        frappe.throw(f"Lisans aktivasyonu başarısız: {e}")


@frappe.whitelist(methods=["POST"])
def deactivate(license_key: str | None = None) -> Dict[str, Any]:
    st = _settings()
    key = (license_key or getattr(st, "license_key", "") or "").strip()
    if not key:
        frappe.throw("Lisans anahtarı gerekli.")
    _ensure_instance_id(); st.reload()
    pid = _get_product_id()
    iid = st.instance_id
    url = DEFAULT_DEACTIVATE_URL
    try:
        payload = {"license_key": key, "instance_id": iid, "product_id": pid}
        resp = _post(url, key, payload)
        data = resp.json() if resp.content else {}
        ok = resp.ok and (data.get("status") in ("deactivated",) or data.get("success") is True)
        if ok:
            st.last_check_on = now_datetime(); st.last_check_status = "INVALID"
            st.save(ignore_permissions=True); frappe.db.commit()
            frappe.cache().set_value(CACHE_STATUS_KEY, "invalid")
            frappe.cache().set_value(CACHE_LAST_CHECK, int(time.time()))
            _write_audit("Deactivate", "OK", "Server", key, {"http": resp.status_code, "raw": data})
            return {"ok": True, "status": "deactivated", "data": data}
        else:
            st.last_check_on = now_datetime(); st.last_check_status = "INVALID"
            st.save(ignore_permissions=True); frappe.db.commit()
            _write_audit("Deactivate", "FAIL", "Server", key, {"http": resp.status_code, "raw": data})
            return {"ok": False, "status": "failed", "data": data}
    except (RequestException, Timeout) as e:
        st.last_check_on = now_datetime(); st.last_check_status = "NETWORK_ERROR"
        st.save(ignore_permissions=True); frappe.db.commit()
        _write_audit("Deactivate", "FAIL", "Server", key, {"err": str(e)})
        frappe.throw(f"Lisans deaktivasyonu başarısız: {e}")


@frappe.whitelist(methods=["GET", "POST"])
def verify(license_key: str | None = None, update_settings: int | bool = 1) -> Dict[str, Any]:
    """TR: Lisans doğrulama (server → valid/grace/invalid). 
    update_settings=0 ise sadece cache/audit güncellenir, Settings yazılmaz."""
    # 1) TR: Parametreleri ve ayarları hazırla
    st = _settings()  # TR: Single Settings dokümanı
    key = (license_key or getattr(st, "license_key", "") or "").strip()  # TR: Lisans anahtarı
    if not key:
        frappe.throw("Lisans anahtarı gerekli.")  # TR: Zorunlu alan
    _ensure_instance_id(); st.reload()  # TR: instance_id üret ve en güncel veriyi al
    iid = st.instance_id
    pid = _get_product_id()
    url = DEFAULT_VERIFY_URL
    upd = bool(int(update_settings)) if isinstance(update_settings, (int, str)) else bool(update_settings)  # TR: bayrak normalize

    try:
        # 2) TR: Sunucuya doğrulama isteği gönder
        payload = {"license_key": key, "instance_id": iid, "product_id": pid}  # TR: minimal yük
        resp = _post(url, key, payload)  # TR: domain doğrulamalı HTTP POST
        data = resp.json() if resp.content else {}

        # 3) TR: Kara liste / revoke kontrolü → doğrudan INVALID
        if _is_revoked(data):
            frappe.cache().set_value(CACHE_STATUS_KEY, "invalid")
            frappe.cache().set_value(CACHE_LAST_CHECK, int(time.time()))
            if upd:
                st.last_check_on = now_datetime(); st.last_check_status = "INVALID"; st.save(ignore_permissions=True); frappe.db.commit()
            _write_audit("Verify", "FAIL", "Server", key, {"reason": "revoked", "raw": data})
            return {"ok": False, "status": "invalid", "data": data}

        # 4) TR: Sunucu 'valid' sayılıyor mu?
        server_valid = (
            resp.ok and (
                data.get("valid") is True or
                str(data.get("status")).lower() in ("active", "valid", "ok") or
                str(data.get("license_status")).lower() in ("active", "activated")
            )
        )

        # 5) TR: Geçerlilik/expiry bilgisi
        exp_raw = _extract_expiry(data) or (st.expires_at and st.expires_at.isoformat())
        exp_dt = get_datetime(exp_raw) if exp_raw else None

        # 6) TR: Sunucu VALID ise cache=valid; Settings yaz (opsiyonel) ve GRACE kilidini kaldır
        if server_valid:
            if upd and exp_dt:
                st.expires_at = exp_dt
                st.grace_locked_days = 0          # TR: tekrar valid olunca kilidi temizle
                st.grace_started_on = None
                st.grace_until = None
            frappe.cache().set_value(CACHE_STATUS_KEY, "valid")
            frappe.cache().set_value(CACHE_LAST_CHECK, int(time.time()))
            if upd:
                st.last_check_on = now_datetime(); st.last_check_status = "VALID"; st.save(ignore_permissions=True); frappe.db.commit()
            _write_audit("Verify", "OK", "Server", key, {"http": resp.status_code, "raw": data})
            return {"ok": True, "status": "valid", "data": data}

        # 7) TR: Sunucu valid değilse; expiry varsa grace penceresini kontrol et
        if exp_dt:
            in_grace, grace_until = _grace_window(exp_dt)
            if in_grace:
                # 7.a) TR: İlk kez GRACE'e düşüyorsak süreyi kilitle
                if upd and cint(getattr(st, "grace_locked_days", 0)) == 0:
                    locked = cint(getattr(st, "billing_grace_days", None) or BILLING_GRACE_DAYS)
                    st.grace_locked_days = locked
                    st.grace_started_on = now_datetime()
                    st.grace_until = grace_until
                frappe.cache().set_value(CACHE_STATUS_KEY, "grace")
                frappe.cache().set_value(CACHE_LAST_CHECK, int(time.time()))
                if upd:
                    st.last_check_on = now_datetime(); st.last_check_status = "GRACE"; st.save(ignore_permissions=True); frappe.db.commit()
                _write_audit("Verify", "GRACE", "Server", key, {
                    "expired_at": _iso(exp_dt),                 # was: exp_dt.isoformat()
                    "grace_until": _iso(grace_until),           # was: grace_until.isoformat()
                    "raw": data,
                })
                return {
                    "ok": True,
                    "status": "grace",
                    "expired_at": _iso(exp_dt),                 # was: exp_dt.isoformat()
                    "grace_until": _iso(grace_until),           # was: grace_until.isoformat()
                    "data": data,
                }


        # 8) TR: Ne valid ne de grace → INVALID
        frappe.cache().set_value(CACHE_STATUS_KEY, "invalid")
        frappe.cache().set_value(CACHE_LAST_CHECK, int(time.time()))
        if upd:
            st.last_check_on = now_datetime(); st.last_check_status = "INVALID"; st.save(ignore_permissions=True); frappe.db.commit()
        _write_audit("Verify", "FAIL", "Server", key, {"http": resp.status_code, "raw": data})
        return {"ok": False, "status": "invalid", "data": data}

    except (RequestException, Timeout) as e:
        # 9) TR: Ağ hatasında yerel expiry ile grace kontrolü yap
        exp_raw = getattr(st, "expires_at", None)
        exp_dt = get_datetime(exp_raw) if exp_raw else None
        if exp_dt:
            in_grace, grace_until = _grace_window(exp_dt)
            if in_grace:
                # 9.a) TR: İlk GRACE kilidini at
                if upd and cint(getattr(st, "grace_locked_days", 0)) == 0:
                    locked = cint(getattr(st, "billing_grace_days", None) or BILLING_GRACE_DAYS)
                    st.grace_locked_days = locked
                    st.grace_started_on = now_datetime()
                    st.grace_until = grace_until
                frappe.cache().set_value(CACHE_STATUS_KEY, "grace")
                if upd:
                    st.last_check_on = now_datetime(); st.last_check_status = "GRACE"; st.save(ignore_permissions=True); frappe.db.commit()
                # --- except (RequestException, Timeout) bloğu içinde GRACE dönüşü ---
                _write_audit("Verify", "GRACE", "Server", key, {
                    "network_error": str(e),
                    "expired_at": _iso(exp_dt),                 # was: exp_dt.isoformat()
                    "grace_until": _iso(grace_until),           # was: grace_until.isoformat()
                })
                return {
                    "ok": True,
                    "status": "grace",
                    "expired_at": _iso(exp_dt),                 # was: exp_dt.isoformat()
                    "grace_until": _iso(grace_until),           # was: grace_until.isoformat()
                    "error": str(e),
                }

        # 9.b) TR: Ne yerel grace ne de valid → network_error
        if upd:
            st.last_check_on = now_datetime(); st.last_check_status = "NETWORK_ERROR"; st.save(ignore_permissions=True); frappe.db.commit()
        _write_audit("Verify", "FAIL", "Server", key, {"err": str(e)})
        return {"ok": False, "status": "network_error", "error": str(e)}

    except Exception as e:
        # 10) TR: Diğer istisnalarda da benzer yerel grace kontrolü
        if isinstance(e, frappe.PermissionError):
            raise  # TR: Domain ihlali vs. üst katmana aynen ilet
        exp_raw = getattr(st, "expires_at", None)
        exp_dt = get_datetime(exp_raw) if exp_raw else None
        if exp_dt:
            in_grace, grace_until = _grace_window(exp_dt)
            if in_grace:
                if upd and cint(getattr(st, "grace_locked_days", 0)) == 0:
                    locked = cint(getattr(st, "billing_grace_days", None) or BILLING_GRACE_DAYS)
                    st.grace_locked_days = locked
                    st.grace_started_on = now_datetime()
                    st.grace_until = grace_until
                frappe.cache().set_value(CACHE_STATUS_KEY, "grace")
                if upd:
                    st.last_check_on = now_datetime(); st.last_check_status = "GRACE"; st.save(ignore_permissions=True); frappe.db.commit()
                _write_audit("Verify", "GRACE", "Server", key, {
                    "exception": str(e),
                    "expired_at": _iso(exp_dt),                 # was: exp_dt.isoformat()
                    "grace_until": _iso(grace_until),           # was: grace_until.isoformat()
                })
                return {
                    "ok": True,
                    "status": "grace",
                    "expired_at": _iso(exp_dt),                 # was: exp_dt.isoformat()
                    "grace_until": _iso(grace_until),           # was: grace_until.isoformat()
                    "error": str(e),
                }

        if upd:
            st.last_check_on = now_datetime(); st.last_check_status = "NETWORK_ERROR"; st.save(ignore_permissions=True); frappe.db.commit()
        _write_audit("Verify", "FAIL", "Server", key, {"err": str(e)})
        return {"ok": False, "status": "network_error", "error": str(e)}


# TR: Scheduler helper (saatlik)
def verify_and_update():
    try:
        return verify()
    except Exception as e:
        frappe.log_error(f"License verify error: {e}", "HelpdeskAI License")
        return {"ok": False, "status": "exception", "error": str(e)}


# TR: Gatekeeper — 'valid' VEYA 'grace' durumlarını kabul eder

@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def gatekeeper() -> Dict[str, Any]:
    # TR: UI'da kaydetme çatışmalarını önlemek için burada Settings'e YAZMAYIZ.
    status = (frappe.cache().get_value(CACHE_STATUS_KEY) or "unknown").lower()
    last = int(frappe.cache().get_value(CACHE_LAST_CHECK) or 0)

    # TR: Cache yoksa veya 1 saatten eskiyse 'hafif doğrulama' yap (update_settings=0)
    if (not status or status == "unknown") or (int(time.time()) - last) > 3600:
        try:
            res = verify(update_settings=0)
            status = res.get("status", status).lower()
        except Exception:
            # TR: ağ hatasında mevcut cache neyse onu kullan
            pass

    return {"ok": status in ("valid", "grace"), "status": status}
