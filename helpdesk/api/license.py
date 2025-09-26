# -*- coding: utf-8 -*-
# TR: HelpdeskAI lisans akışları – LMFWC v2 REST API uyarlaması
from __future__ import annotations
import json, uuid, time, os, hashlib, socket, platform
from typing import Dict, Any, Tuple, Optional
from urllib.parse import urlparse
import requests
from requests.auth import HTTPBasicAuth
from requests.exceptions import RequestException, Timeout
import frappe
from frappe.utils import now_datetime, get_datetime, add_days

# ---------------------------------------------------------------------------
# TR: Uç noktalar (LMFWC v2)
#   Referans: /wp-json/lmfwc/v2/licenses/{activate|reactivate|deactivate|validate}/{license_key}
#   Not: Domain müşteri mağazasıdır; biz brvsoftware.com kullanıyoruz.
LMFWC_BASE = "https://brvsoftware.com/wp-json/lmfwc/v2/licenses"
LMFWC_ACTIVATE_URL   = LMFWC_BASE + "/activate/{license_key}"      # L: Aktivasyon (token üretir)
LMFWC_REACTIVATE_URL = LMFWC_BASE + "/reactivate/{license_key}"    # L: Re-aktivasyon (mevcut token ile)
LMFWC_DEACTIVATE_URL = LMFWC_BASE + "/deactivate/{license_key}"    # L: Deaktivasyon (token ile tekil, tokensiz tümü)
LMFWC_VALIDATE_URL   = LMFWC_BASE + "/validate/{license_key}"      # L: Doğrulama

# TR: Cache anahtarları
CACHE_STATUS_KEY = "helpdesk:license:status"          # L: 'valid' | 'grace' | 'invalid' | 'unknown'
CACHE_LAST_CHECK = "helpdesk:license:last_check_ts"   # L: epoch ts

# TR: Grace (gün)
BILLING_GRACE_DAYS = 30  # L: Sunucu ulaşılamazsa son başarılı validate'ten itibaren 30 gün

# ---------------------------------------------------------------------------
# TR: Settings dokümanı

def _settings():
    return frappe.get_single("HelpdeskAI Settings")  # L: Single doctype

# ---------------------------------------------------------------------------
# TR: Domain doğrulama – sadece beklenen mağaza domainine izin

def _assert_expected_domain(url: str):
    netloc = urlparse(url).netloc.lower()
    if netloc != "brvsoftware.com":
        raise frappe.PermissionError(f"Beklenen domain brvsoftware.com; görülen: {netloc}")

# ---------------------------------------------------------------------------
# TR: ISO helpers

def _iso(dt) -> str | None:
    if not dt:
        return None
    try:
        return get_datetime(dt).isoformat()
    except Exception:
        try:
            return dt.isoformat()
        except Exception:
            return str(dt)

# ---------------------------------------------------------------------------
# TR: Cihaz parmak izi (stabil)

def _sha256_hex(s: bytes) -> str:
    return hashlib.sha256(s).hexdigest()


def _stable_fingerprint() -> str:
    """TR: Platforma göre kararlı fingerprint üretir (Linux/macos/Windows)."""
    host = socket.gethostname() or "unknown"
    sys = platform.system().lower()
    raw = ""
    try:
        if sys == "linux":
            with open("/etc/machine-id", "r") as f:
                mid = f.read().strip()
            raw = f"{mid}::{host}"
        elif sys == "darwin":  # macOS
            try:
                import subprocess, re
                io = subprocess.check_output(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"]).decode()
                m = re.search(r'IOPlatformUUID\"\s*=\s*\"([^\"]+)\"', io)
                uuid_ = m.group(1) if m else "unknown"
            except Exception:
                uuid_ = "unknown"
            raw = f"{uuid_}::{host}"
        elif sys == "windows":
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\\Microsoft\\Cryptography")
                machine_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            except Exception:
                machine_guid = str(uuid.uuid4())
            raw = f"{machine_guid}::{host}"
        else:
            raw = f"{sys}::{host}::{uuid.uuid4()}"  # L: Fallback
    except Exception:
        raw = f"fallback::{host}::{uuid.uuid4()}"

    st = _settings()
    salt = getattr(st, "site_salt", "") or ""
    return _sha256_hex((salt + "::" + raw).encode("utf-8"))


def _ensure_device_fingerprint() -> str:
    """TR: Settings'te yoksa üretip yazar, varsa aynen döner."""
    st = _settings()
    fp = (getattr(st, "device_fingerprint", "") or "").strip()
    if not fp:
        fp = _stable_fingerprint()
        st.device_fingerprint = fp
        st.save(ignore_permissions=True)
        frappe.db.commit()
    return fp

# ---------------------------------------------------------------------------
# TR: Tarih yardımcıları (genel)

def _add_days(base, days) -> Optional[str]:  # [L2] Basit yardımcı – modül geneli
    try:
        return add_days(get_datetime(base), int(days)).isoformat()
    except Exception:
        return None

# ---------------------------------------------------------------------------
# TR: Uygulama versiyonu

def _app_version() -> str:
    try:
        return frappe.utils.get_full_version()
    except Exception:
        return "unknown"

# ---------------------------------------------------------------------------
# TR: HTTP yardımcıları (LMFWC v2 – GET + HTTP Basic Auth)

_DEF_TIMEOUT = 15


def _lm_auth() -> HTTPBasicAuth | None:
    """Öncelik: ENV → site_config → Settings"""
    # 1) ENV
    ck = (os.getenv("LMFWC_CONSUMER_KEY") or "").strip()
    cs = (os.getenv("LMFWC_CONSUMER_SECRET") or "").strip()
    # 2) site_config.json
    if not (ck and cs):
        conf = frappe.conf or {}
        ck = ck or (conf.get("lmfwc_consumer_key") or "").strip()
        cs = cs or (conf.get("lmfwc_consumer_secret") or "").strip()
    # 3) HelpdeskAI Settings
    if not (ck and cs):
        st = _settings()
        ck = ck or (getattr(st, "lmfwc_consumer_key", "") or "").strip()
        cs = cs or (getattr(st, "lmfwc_consumer_secret", "") or "").strip()
    return HTTPBasicAuth(ck, cs) if (ck and cs) else None



def _get(url: str, params: Dict[str, Any] | None = None, timeout: int = _DEF_TIMEOUT) -> requests.Response:
    _assert_expected_domain(url)
    auth = _lm_auth()
    resp = requests.get(url, params=(params or {}), timeout=timeout, allow_redirects=True, auth=auth)
    final_netloc = urlparse(resp.url).netloc.lower()
    if final_netloc != "brvsoftware.com":
        raise frappe.PermissionError(f"Yanıt domain’i beklenen değil: {final_netloc}")
    return resp

# ---------------------------------------------------------------------------
# TR: License Audit Log yazımı (özet + maskeleme)

def _write_audit(action: str, status: str, source: str, license_key: str | None = None, extra: Dict[str, Any] | None = None):
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
    doc.app_version = _app_version()
    if extra:
        doc.notes = json.dumps(extra, ensure_ascii=False)[:1400]
    try:
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()

# ---------------------------------------------------------------------------
# TR: Grace hesaplama — son başarılı validate zamanına göre

def _grace_by_last_ok(last_ok_dt) -> Tuple[bool, Any]:
    if not last_ok_dt:
        return (False, None)
    last = get_datetime(last_ok_dt)
    grace_until = add_days(last, BILLING_GRACE_DAYS)
    return (now_datetime() <= get_datetime(grace_until), grace_until)

# ---------------------------------------------------------------------------
# TR: Yanıt normalizasyonu (LMFWC v2 success/data yapısı)

def _json(resp: requests.Response) -> Dict[str, Any]:
    try:
        return resp.json() if resp.content else {}
    except Exception:
        return {}


def _lm_ok(data: Dict[str, Any]) -> bool:
    return bool((data or {}).get("success") is True)


def _derive_expiry(payload: Dict[str, Any]) -> Optional[str]:
    """LMFWC yanıtından bitiş tarihini bulur veya türetir.
    Öncelik sırası:
      1) data.expiresAt
      2) valid_for (gün) + createdAt
      3) valid_for (gün) + ilk aktif activationData.activated_at
    Dönüş: ISO string (UTC/naive) veya None
    """
    if not payload:
        return None

    # 1) Doğrudan expiresAt
    exp = payload.get("expiresAt") or payload.get("expires_at")
    if exp:
        try:
            return get_datetime(exp).isoformat()
        except Exception:
            return None

    # 2) valid_for + createdAt
    valid_for = (
        payload.get("valid_for")
        or payload.get("validFor")
        or payload.get("valid_days")
        or payload.get("validDays")
    )
    created = (
        payload.get("createdAt")
        or payload.get("created_at")
        or payload.get("issued_at")
    )

    # 2a) createdAt varsa ondan türet
    if valid_for and created:
        iso = _add_days(created, valid_for)
        if iso:
            return iso

    # 3) valid_for + activation.activated_at
    if valid_for:
        act_list = payload.get("activationData") or payload.get("activations") or []
        try:
            first_active = None
            for a in act_list:
                if not a.get("deactivated_at"):
                    first_active = a
                    break
            if first_active is None and act_list:
                first_active = act_list[0]

            act_at = None
            if first_active:
                act_at = (
                    first_active.get("activated_at")
                    or first_active.get("activatedAt")
                    or first_active.get("created_at")
                )
            if act_at:
                iso = _add_days(act_at, valid_for)
                if iso:
                    return iso
        except Exception:
            return None

    # 4) Bulunamazsa None
    return None


# ---------------------------------------------------------------------------
# TR: Public API – Activate / Reactivate / Deactivate / Validate

@frappe.whitelist(methods=["POST"])
def activate(license_key: str | None = None) -> Dict[str, Any]:
    st = _settings()
    key = (license_key or getattr(st, "license_key", "") or "").strip()
    if not key:
        frappe.throw("Lisans anahtarı gerekli.")

    fp = _ensure_device_fingerprint()  # L: etiketleme için kullanacağız
    st.reload()

    url = LMFWC_ACTIVATE_URL.format(license_key=key)
    try:
        # TR: İsteğe bağlı parametreler – label/meta_data ile cihaz izini bırakıyoruz.
        params = {
            "label": f"helpdesk::{fp[:12]}",
            "meta_data": json.dumps({"device_fingerprint": fp, "app_version": _app_version()}),
        }
        resp = _get(url, params=params)
        data = _json(resp)

        if resp.ok and _lm_ok(data):
            payload = (data.get("data") or {})
            # TR: Aktivasyon dönen şema: activationData.token (tekil obje)
            act = payload.get("activationData") or {}
            token = act.get("token")
            exp = _derive_expiry(payload)

            st.activation_token = token or getattr(st, "activation_token", None)
            if exp:
                try:
                    st.expires_at = get_datetime(exp)
                except Exception:
                    pass
            st.last_ok_on = now_datetime()
            st.last_check_on = now_datetime(); st.last_check_status = "VALID"
            st.device_fingerprint = fp
            st.save(ignore_permissions=True); frappe.db.commit()

            frappe.cache().set_value(CACHE_STATUS_KEY, "valid")
            frappe.cache().set_value(CACHE_LAST_CHECK, int(time.time()))

            _write_audit("Activate", "OK", "Server", key, {"http": resp.status_code, "raw": data})
            return {"ok": True, "status": "activated", "data": data}

        # TR: Başarısızlık
        st.last_check_on = now_datetime(); st.last_check_status = "INVALID"
        st.save(ignore_permissions=True); frappe.db.commit()
        frappe.cache().set_value(CACHE_STATUS_KEY, "invalid")
        _write_audit("Activate", "FAIL", "Server", key, {"http": resp.status_code, "raw": data})
        return {"ok": False, "status": (data.get("message") or "invalid"), "data": data}

    except (RequestException, Timeout) as e:
        st.last_check_on = now_datetime(); st.last_check_status = "NETWORK_ERROR"
        st.save(ignore_permissions=True); frappe.db.commit()
        _write_audit("Activate", "FAIL", "Server", key, {"err": str(e)})
        frappe.throw(f"Lisans aktivasyonu başarısız: {e}")


@frappe.whitelist(methods=["POST"])
def reactivate(license_key: str | None = None) -> Dict[str, Any]:
    """TR: Mevcut aktivasyonu yeniden etkinleştir (token ile)."""
    st = _settings()
    key = (license_key or getattr(st, "license_key", "") or "").strip()
    if not key:
        frappe.throw("Lisans anahtarı gerekli.")
    token = (getattr(st, "activation_token", "") or "").strip()
    if not token:
        frappe.throw("Activation token bulunamadı. Önce activate çağrısı yapın.")

    url = LMFWC_REACTIVATE_URL.format(license_key=key)
    try:
        params = {
            "token": token,
            "meta_data": json.dumps({"reactivate": True, "app_version": _app_version()}),
        }
        resp = _get(url, params=params)
        data = _json(resp)
        if resp.ok and _lm_ok(data):
            payload = (data.get("data") or {})
            act = payload.get("activationData") or {}
            tok2 = act.get("token") or token
            exp = _derive_expiry(payload)
            st.activation_token = tok2
            if exp:
                st.expires_at = get_datetime(exp)

            st.last_ok_on = now_datetime()
            st.last_check_on = now_datetime(); st.last_check_status = "VALID"
            st.save(ignore_permissions=True); frappe.db.commit()
            frappe.cache().set_value(CACHE_STATUS_KEY, "valid")
            frappe.cache().set_value(CACHE_LAST_CHECK, int(time.time()))
            _write_audit("Reactivate", "OK", "Server", key, {"http": resp.status_code, "raw": data})
            return {"ok": True, "status": "reactivated", "data": data}

        st.last_check_on = now_datetime(); st.last_check_status = "INVALID"
        st.save(ignore_permissions=True); frappe.db.commit()
        _write_audit("Reactivate", "FAIL", "Server", key, {"http": resp.status_code, "raw": data})
        return {"ok": False, "status": (data.get("message") or "failed"), "data": data}

    except (RequestException, Timeout) as e:
        st.last_check_on = now_datetime(); st.last_check_status = "NETWORK_ERROR"
        st.save(ignore_permissions=True); frappe.db.commit()
        _write_audit("Reactivate", "FAIL", "Server", key, {"err": str(e)})
        frappe.throw(f"Lisans re-aktivasyonu başarısız: {e}")


@frappe.whitelist(methods=["POST"])
def deactivate(license_key: str | None = None) -> Dict[str, Any]:
    # TR: LMFWC v2 – token verilirse tekil aktivasyon; verilmezse tüm aktivasyonlar.
    st = _settings()
    key = (license_key or getattr(st, "license_key", "") or "").strip()
    if not key:
        frappe.throw("Lisans anahtarı gerekli.")

    token = (getattr(st, "activation_token", "") or "").strip()
    url = LMFWC_DEACTIVATE_URL.format(license_key=key)
    try:
        params = {"token": token} if token else None
        resp = _get(url, params=params)
        data = _json(resp)

        if resp.ok and _lm_ok(data):
            st.activation_token = None
            st.last_check_on = now_datetime(); st.last_check_status = "INVALID"
            st.save(ignore_permissions=True); frappe.db.commit()
            frappe.cache().set_value(CACHE_STATUS_KEY, "invalid")
            frappe.cache().set_value(CACHE_LAST_CHECK, int(time.time()))
            _write_audit("Deactivate", "OK", "Server", key, {"http": resp.status_code, "raw": data})
            return {"ok": True, "status": "deactivated", "data": data}

        st.last_check_on = now_datetime(); st.last_check_status = "INVALID"
        st.save(ignore_permissions=True); frappe.db.commit()
        _write_audit("Deactivate", "FAIL", "Server", key, {"http": resp.status_code, "raw": data})
        return {"ok": False, "status": (data.get("message") or "failed"), "data": data}

    except (RequestException, Timeout) as e:
        st.last_check_on = now_datetime(); st.last_check_status = "NETWORK_ERROR"
        st.save(ignore_permissions=True); frappe.db.commit()
        _write_audit("Deactivate", "FAIL", "Server", key, {"err": str(e)})
        frappe.throw(f"Lisans deaktivasyonu başarısız: {e}")


@frappe.whitelist(methods=["GET", "POST"])
def validate(license_key: str | None = None, update_settings: int | bool = 1) -> Dict[str, Any]:
    """TR: Lisans doğrulama (LMFWC v2 /validate). Sunucuya ulaşılamazsa GRACE: last_ok_on + 30g."""
    st = _settings()
    key = (license_key or getattr(st, "license_key", "") or "").strip()
    if not key:
        frappe.throw("Lisans anahtarı gerekli.")

    fp = _ensure_device_fingerprint()
    st.reload()
    upd = bool(int(update_settings)) if isinstance(update_settings, (int, str)) else bool(update_settings)

    url = LMFWC_VALIDATE_URL.format(license_key=key)
    try:
        resp = _get(url)
        data = _json(resp)

        if resp.ok and _lm_ok(data):
            payload = (data.get("data") or {})
            exp_raw = _derive_expiry(payload) or payload.get("expiresAt")
            # TR: Basit geçerlilik kabulü – success:true
            if upd:
                if exp_raw:
                    try:
                        st.expires_at = get_datetime(exp_raw)
                    except Exception:
                        pass
                st.last_ok_on = now_datetime()
                st.last_check_on = now_datetime(); st.last_check_status = "VALID"
                st.device_fingerprint = fp
                # TR: Varsa ilk aktif activationData token'ını sakla
                act_list = payload.get("activationData") or []
                try:
                    active_rec = next((a for a in act_list if not a.get("deactivated_at")), None)
                    if active_rec and active_rec.get("token"):
                        st.activation_token = active_rec.get("token")
                except Exception:
                    pass
                st.save(ignore_permissions=True); frappe.db.commit()
            frappe.cache().set_value(CACHE_STATUS_KEY, "valid"); frappe.cache().set_value(CACHE_LAST_CHECK, int(time.time()))
            _write_audit("Validate", "OK", "Server", key, {"http": resp.status_code, "raw": data})
            return {"ok": True, "status": "valid", "data": data}

        # TR: Sunucu success:false → invalid
        if resp.ok and not _lm_ok(data):
            if upd:
                st.last_check_on = now_datetime(); st.last_check_status = "INVALID"; st.save(ignore_permissions=True); frappe.db.commit()
            frappe.cache().set_value(CACHE_STATUS_KEY, "invalid"); frappe.cache().set_value(CACHE_LAST_CHECK, int(time.time()))
            _write_audit("Validate", "FAIL", "Server", key, {"http": resp.status_code, "raw": data})
            return {"ok": False, "status": (data.get("message") or "invalid"), "data": data}

        # TR: Aksi durumlarda invalid'e düş
        if upd:
            st.last_check_on = now_datetime(); st.last_check_status = "INVALID"; st.save(ignore_permissions=True); frappe.db.commit()
        frappe.cache().set_value(CACHE_STATUS_KEY, "invalid"); frappe.cache().set_value(CACHE_LAST_CHECK, int(time.time()))
        _write_audit("Validate", "FAIL", "Server", key, {"http": getattr(resp, 'status_code', None), "raw": data})
        return {"ok": False, "status": "invalid", "data": data}

    except (RequestException, Timeout) as e:
        # TR: Ağ hatasında GRACE: last_ok_on + 30 gün
        last_ok = getattr(st, "last_ok_on", None)
        in_grace, grace_until = _grace_by_last_ok(last_ok)
        if in_grace:
            if upd:
                st.last_check_on = now_datetime(); st.last_check_status = "GRACE"; st.grace_until = grace_until; st.save(ignore_permissions=True); frappe.db.commit()
            frappe.cache().set_value(CACHE_STATUS_KEY, "grace"); frappe.cache().set_value(CACHE_LAST_CHECK, int(time.time()))
            _write_audit("Validate", "GRACE", "Server", key, {"network_error": str(e), "last_ok_on": _iso(last_ok), "grace_until": _iso(grace_until)})
            return {"ok": True, "status": "grace", "last_ok_on": _iso(last_ok), "grace_until": _iso(grace_until), "error": str(e)}
        if upd:
            st.last_check_on = now_datetime(); st.last_check_status = "NETWORK_ERROR"; st.save(ignore_permissions=True); frappe.db.commit()
        _write_audit("Validate", "FAIL", "Server", key, {"err": str(e)})
        return {"ok": False, "status": "network_error", "error": str(e)}

    except Exception as e:
        if isinstance(e, frappe.PermissionError):
            raise
        last_ok = getattr(st, "last_ok_on", None)
        in_grace, grace_until = _grace_by_last_ok(last_ok)
        if in_grace:
            if upd:
                st.last_check_on = now_datetime(); st.last_check_status = "GRACE"; st.grace_until = grace_until; st.save(ignore_permissions=True); frappe.db.commit()
            frappe.cache().set_value(CACHE_STATUS_KEY, "grace"); frappe.cache().set_value(CACHE_LAST_CHECK, int(time.time()))
            _write_audit("Validate", "GRACE", "Server", key, {"exception": str(e), "last_ok_on": _iso(last_ok), "grace_until": _iso(grace_until)})
            return {"ok": True, "status": "grace", "last_ok_on": _iso(last_ok), "grace_until": _iso(grace_until), "error": str(e)}
        if upd:
            st.last_check_on = now_datetime(); st.last_check_status = "NETWORK_ERROR"; st.save(ignore_permissions=True); frappe.db.commit()
        _write_audit("Validate", "FAIL", "Server", key, {"err": str(e)})
        return {"ok": False, "status": "network_error", "error": str(e)}


# TR: Scheduler helper (saatlik)

def validate_and_update():
    try:
        return validate()
    except Exception as e:
        frappe.log_error(f"License validate error: {e}", "HelpdeskAI License")
        return {"ok": False, "status": "exception", "error": str(e)}


# TR: Gatekeeper — 'valid' VEYA 'grace' kabul
@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])

def gatekeeper() -> Dict[str, Any]:
    GRACE_RECHECK_SECONDS = 6 * 3600
    NOW = int(time.time())

    status = (frappe.cache().get_value(CACHE_STATUS_KEY) or "unknown").lower()
    last   = int(frappe.cache().get_value(CACHE_LAST_CHECK) or 0)

    if status == "grace":
        stale = (NOW - last) > GRACE_RECHECK_SECONDS
    else:
        stale = (NOW - last) > 3600 or (not status or status == "unknown")

    if stale:
        try:
            res = validate(update_settings=0)
            status = (res or {}).get("status", status).lower()
            frappe.cache().set_value(CACHE_LAST_CHECK, NOW)
        except Exception:
            pass

    return {"ok": status in ("valid", "grace"), "status": status}


# --- Geriye dönük uyumluluk ---
@frappe.whitelist(methods=["GET", "POST"])  

def verify(license_key: str | None = None, update_settings: int | bool = 1):
    return validate(license_key=license_key, update_settings=update_settings)


def verify_and_update():
    return validate_and_update()
