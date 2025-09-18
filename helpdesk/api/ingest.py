# -*- coding: utf-8 -*-
"""
Helpdesk – Integration API (hafif, lisans kontrolü yok).
- GET uç noktaları: takımlar, takım üyeleri, biletler, makaleler, routing context
- POST/PUT uç noktaları: tek bilet alanlarını bağımsız güncelle (summary, sentiment, route, öneriler, metrikler)
- Genel "update_ticket" ile whitelist edilmiş alanlarda toplu/parsiyel güncelleme de mümkün.

NOT: Güvenlik için ileride API Key/Secret eklenecek. Şimdilik açık (allow_guest=True).
"""
from __future__ import annotations

# (1) TR: Tipler ve yardımcılar
from typing import Any, Dict, List, Iterable
import json
import re

import frappe
from frappe.utils import cint, flt, cstr

# --- AI Interaction Log (MERKEZİ) -------------------------------------------
# (L01) AI log yazımı için tek import — mevcut dosyayı bozmadan sadece ekleme
try:
    from helpdesk.api.ai_log import write as ai_log_write  # (L02) Merkezi yazıcı
except Exception:  # (L03) Emniyet: import başarısızsa no-op fonksiyon
    def ai_log_write(*args, **kwargs):  # type: ignore
        try:
            frappe.log_error("ai_log import failed", "HelpdeskAI")
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------

def _settings():
    """HelpdeskAI Settings tekil dokümanı (varsa)."""
    try:
        return frappe.get_single("HelpdeskAI Settings")
    except Exception:
        return None


def _is_shadow(ticket_name: str | None = None) -> bool:
    """Global veya ticket bazlı shadow aktif mi?"""
    try:
        st = _settings()
        if st and cint(getattr(st, "shadow_mode", 0)):
            return True
    except Exception:
        pass
    if ticket_name:
        try:
            v = frappe.db.get_value("HD Ticket", ticket_name, "shadow_mode")
            return bool(cint(v or 0))
        except Exception:
            pass
    return False


def _clean_html(text: str) -> str:
    """HTML/etiket temizleme (metni bozma)."""
    if text is None:
        return ""
    try:
        # Frappe 14/15
        from frappe.utils import strip_html
        return strip_html(text)
    except Exception:
        try:
            from frappe.utils import strip_html_tags
            return strip_html_tags(text)
        except Exception:
            return re.sub(r"<[^>]+>", "", cstr(text))


def _get_doc(doctype: str, name: str):
    doc = frappe.get_doc(doctype, name)
    if not doc:
        frappe.throw(f"{doctype} {name} not found")
    return doc


def _parse_fields_arg(fields: Any) -> Dict[str, Any]:
    """fields parametresi string JSON geldiyse dict'e çevirir."""
    if isinstance(fields, (dict, list)):
        return fields
    if fields is None:
        return {}
    if isinstance(fields, str):
        fields = fields.strip()
        if not fields:
            return {}
        try:
            return json.loads(fields)
        except Exception:
            frappe.throw("Invalid JSON for `fields`")
    return {}


def _pluck(lst: Iterable[Dict[str, Any]], key: str) -> List[Any]:
    return [r.get(key) for r in lst or [] if r.get(key)]


# ---------------------------------------------------------------------------
# GET – KATALOG / LİSTELER
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_teams(include_members: int | bool = 0, include_tags: int | bool = 0):
    # TR: Takım listesi, opsiyonel üye detayları
    doctype = "HD Team"
    fields = ["name"]
    if frappe.db.has_column(doctype, "team_name"):
        fields.append("team_name")
    if frappe.db.has_column(doctype, "description"):
        fields.append("description")

    teams = frappe.get_all(doctype, fields=fields, order_by="modified desc")

    if cint(include_members):
        child_dt = "HD Team Member"
        user_field = "user"
        if frappe.db.table_exists(child_dt):
            by_team = frappe.get_all(child_dt, fields=["parent", user_field], limit=10000)
            members_map: Dict[str, List[str]] = {}
            for row in by_team:
                members_map.setdefault(row["parent"], []).append(row[user_field])
            for t in teams:
                t["members"] = members_map.get(t["name"], [])
        else:
            for t in teams:
                t["members"] = []

    # include_tags: şu an kullanılmıyor
    return {"ok": True, "teams": teams}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_team_members(team: str) -> Dict[str, Any]:
    """Tek takımın üyeleri."""
    members = frappe.get_all(
        "HD Team Member",
        fields=["user"],
        filters={"parent": team, "parenttype": "HD Team"},
        order_by="idx asc",
    )
    return {"ok": True, "team": team, "members": _pluck(members, "user")}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_tickets_by_team(
    team: str,
    status: str | None = None,
    limit: int = 50,
    start: int = 0,
) -> Dict[str, Any]:
    """Takıma atanmış HD Ticket'lar."""
    filters: Dict[str, Any] = {"agent_group": team}
    if status:
        filters["status"] = status

    tickets = frappe.get_all(
        "HD Ticket",
        fields=[
            "name",
            "subject",
            "status",
            "priority",
            "agent_group",
            "customer",
            "opening_date",
            "opening_time",
            "modified",
        ],
        filters=filters,
        limit_start=start,
        limit_page_length=limit,
        order_by="modified desc",
    )
    return {"ok": True, "team": team, "tickets": tickets}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_tickets_by_user(
    user: str,
    status: str | None = None,
    limit: int = 50,
    start: int = 0,
) -> Dict[str, Any]:
    """
    Kullanıcıya atanmış biletler.
    Frappe'de atamalar ToDo üstünden tutulur.
    """
    assigned = frappe.get_all(
        "ToDo",
        fields=["reference_name"],
        filters={
            "reference_type": "HD Ticket",
            "allocated_to": user,
            "status": ["!=", "Closed"],
        },
        limit_page_length=1000,
    )
    ticket_names = _pluck(assigned, "reference_name")
    if not ticket_names:
        return {"ok": True, "user": user, "tickets": []}

    filters: Dict[str, Any] = {"name": ["in", ticket_names]}
    if status:
        filters["status"] = status

    tickets = frappe.get_all(
        "HD Ticket",
        fields=[
            "name",
            "subject",
            "status",
            "priority",
            "agent_group",
            "customer",
            "opening_date",
            "opening_time",
            "modified",
        ],
        filters=filters,
        limit_start=start,
        limit_page_length=limit,
        order_by="modified desc",
    )
    return {"ok": True, "user": user, "tickets": tickets}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_articles(q: str | None = None, limit: int = 50, start: int = 0) -> Dict[str, Any]:
    """
    Bilgi bankası makaleleri (HD Article). Alan adları değişebileceği için
    asgari set döndürülür (name, title, content benzeri).
    """
    candidate_fields = [
        "name", "title", "subject", "article_title", "content", "body", "description", "modified"
    ]
    meta = frappe.get_meta("HD Article")
    fields = [f for f in candidate_fields if meta.has_field(f) or f in ("name", "modified")]

    filters: Dict[str, Any] = {}
    if q:
        like_field = "title" if meta.has_field("title") else ("subject" if meta.has_field("subject") else None)
        if like_field:
            filters[like_field] = ["like", f"%{q}%"]

    res = frappe.get_all(
        "HD Article",
        fields=fields,
        filters=filters,
        limit_start=start,
        limit_page_length=limit,
        order_by="modified desc",
    )
    return {"ok": True, "articles": res}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_ticket(ticket: str, fields: str | None = None) -> Dict[str, Any]:
    """Tek bilet detayları (alan listesi opsiyonel)."""
    default_fields = [
        "name",
        "subject",
        "status",
        "priority",
        "agent_group",
        "customer",
        "description",
        "ai_summary",
        "ai_reply_suggestion",
        "last_sentiment",
        "sentiment_trend",
        "effort_score",
        "effort_band",
        "route_rationale",
        "shadow_mode",
        "cluster_hash",
        "modified",
    ]
    if fields:
        try:
            req = json.loads(fields)
            if isinstance(req, list) and req:
                default_fields = req
        except Exception:
            pass

    doc = frappe.get_value("HD Ticket", ticket, default_fields, as_dict=True)
    if not doc:
        frappe.throw("HD Ticket not found")
    doc["shadow_effective"] = _is_shadow(ticket)
    return {"ok": True, "ticket": doc}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_routing_context():
    ctx: Dict[str, Any] = {}
    ctx["teams"] = get_teams(include_members=1, include_tags=1)
    return {"ok": True, "context": ctx}


# ---------------------------------------------------------------------------
# POST / PUT – TEK BİLET ALANI GÜNCELLEME (bağımsız ve esnek)
# ---------------------------------------------------------------------------

TEXT_FIELDS = {
    "ai_summary",
    "ai_reply_suggestion",
    "route_rationale",
    "sentiment_trend",
}
FLOAT_FIELDS = {
    "route_confidence",
    "effort_score",
    "problem_confidence",
}
SELECT_FIELDS: Dict[str, set[str]] = {
    "last_sentiment": {"Positive", "Neutral", "Negative"},
    "effort_band": {"Low", "Medium", "High"},
}

CHECK_FIELDS = {
    "shadow_mode",
}
DATA_FIELDS = {
    "cluster_hash",
}

LINK_FIELDS: Dict[str, str] = {
    "agent_group": "HD Team",
    "customer": "Customer",
}

ALLOWED_FIELDS = TEXT_FIELDS | FLOAT_FIELDS | set(SELECT_FIELDS) | set(LINK_FIELDS) | CHECK_FIELDS | DATA_FIELDS


# (A) TR: TEXT birleştirme yardımcı fonksiyonu (test edilebilir, yan etkisiz)
def _append_text(base: str, new: str, do_append: bool) -> str:
    base = cstr(base or "")
    new = cstr(new or "")
    if do_append and base:
        return base + "\n" + new  # Satır sonu kontrollü
    return new


def _apply_ticket_updates(
    ticket: str,
    updates: Dict[str, Any],
    append: bool = False,
    clean_html: bool = True,
    respect_shadow: bool = True,
) -> Dict[str, Any]:
    if not updates:
        try:
            ai_log_write(ticket, "update_ticket", status="FAIL", source="ingest",
                         preview=0, request={}, result={"error": "No fields to update"})
        except Exception:
            pass
        return {"ok": False, "error": "No fields to update"}

    doc = _get_doc("HD Ticket", ticket)
    changed: Dict[str, Any] = {}
    shadow = bool(respect_shadow and _is_shadow(ticket))

    for k, v in updates.items():
        if k not in ALLOWED_FIELDS:
            continue
        if k in TEXT_FIELDS:
            val = cstr(v)
            if clean_html:
                val = _clean_html(val)
            base = cstr(getattr(doc, k) or "")
            val = _append_text(base, val, append)  # HATA düzeltildi: doğru string birleştirme
            if not shadow:
                setattr(doc, k, val)
            changed[k] = val
        elif k in FLOAT_FIELDS:
            val = flt(v)
            if not shadow:
                setattr(doc, k, val)
            changed[k] = val
        elif k in SELECT_FIELDS:
            allowed = SELECT_FIELDS[k]
            val = cstr(v)
            if val and val not in allowed:
                frappe.throw(f"Invalid value for {k}. Allowed: {sorted(allowed)}")
            if not shadow:
                setattr(doc, k, val)
            changed[k] = val
        elif k in LINK_FIELDS:
            doctype = LINK_FIELDS[k]
            if v:
                if not frappe.db.exists(doctype, v):
                    frappe.throw(f"Linked doc not found: {doctype} {v}")
                if not shadow:
                    setattr(doc, k, v)
                changed[k] = v
            else:
                if not shadow:
                    setattr(doc, k, None)
                changed[k] = None
        elif k in CHECK_FIELDS:
            val = 1 if cint(v) else 0
            if not shadow:
                setattr(doc, k, val)
            changed[k] = val
        elif k in DATA_FIELDS:
            val = cstr(v)
            if not shadow:
                setattr(doc, k, val)
            changed[k] = val

    if not changed:
        try:
            ai_log_write(ticket, "update_ticket", status="FAIL", source="ingest",
                         preview=0, request=updates, result={"error": "No allowed fields were provided"})
        except Exception:
            pass
        return {"ok": False, "error": "No allowed fields were provided"}

    if shadow:
        try:
            ai_log_write(ticket, "update_ticket", status="WARN", source="ingest",
                         preview=1, request=updates, result={"preview": changed})
        except Exception:
            pass
        return {"ok": True, "ticket": ticket, "shadow": True, "preview": changed}

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    try:
        ai_log_write(ticket, "update_ticket", status="OK", source="ingest",
                     preview=0, request=updates, result={"changed": changed})
    except Exception:
        pass

    return {"ok": True, "ticket": ticket, "changed": changed}


# ---- Kolay uç noktalar -----------------------------------------------------

@frappe.whitelist(allow_guest=True, methods=["POST", "PUT"])
def ingest_summary(
    ticket: str,
    summary: str,
    append: int | bool = 0,
    clean_html: int | bool = 1,
) -> Dict[str, Any]:
    return _apply_ticket_updates(
        ticket,
        {"ai_summary": summary},
        append=cint(append) == 1,
        clean_html=cint(clean_html) == 1,
    )

# --- Problem Ticket UPSERT (merkezi loglama ile) ----------------------------
PROBLEM_TEXT_FIELDS = {
    "subject", "impact", "root_cause", "workaround", "fix_plan", "resolution_summary"
}
PROBLEM_SELECT_FIELDS: Dict[str, set[str]] = {
    "status": {"Open", "Investigating", "Identified", "Monitoring", "Resolved", "Closed"},
    "severity": {"Low", "Medium", "High", "Critical"},
}
PROBLEM_LINK_FIELDS: Dict[str, str] = {
    "owner_team": "HD Team",
    "problem_manager": "User",
}
PROBLEM_DATETIME_FIELDS = {"reported_on", "first_seen_on", "mitigated_on", "resolved_on"}
PROBLEM_INT_FIELDS = {"reopened_count"}


def _find_problem_by_subject(subject: str) -> str | None:
    if not subject:
        return None
    return frappe.db.get_value("Problem Ticket", {"subject": subject}, "name")


def _changed(old, new) -> bool:
    o = (cstr(old) if old is not None else None)
    n = (cstr(new) if new is not None else None)
    return o != n

# --- Problem Ticket READ API'leri ------------------------------------------

@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_problem_ticket(name: str, fields: str | None = None):
    default_fields = [
        "name", "subject", "status", "severity",
        "owner_team", "problem_manager",
        "impact", "root_cause", "workaround", "fix_plan", "resolution_summary",
        "reported_on", "first_seen_on", "mitigated_on", "resolved_on",
        "reopened_count", "modified",
    ]
    if fields:
        try:
            req = json.loads(fields)
            if isinstance(req, list) and req:
                default_fields = req
        except Exception:
            pass

    doc = frappe.get_value("Problem Ticket", name, default_fields, as_dict=True)
    if not doc:
        frappe.throw("Problem Ticket not found")
    return {"ok": True, "problem": doc}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def list_problem_tickets(
    status: str | None = None,
    severity: str | None = None,
    owner_team: str | None = None,
    problem_manager: str | None = None,
    q: str | None = None,
    limit: int = 50,
    start: int = 0,
):
    filters: Dict[str, Any] = {}
    if status:          filters["status"] = status
    if severity:        filters["severity"] = severity
    if owner_team:      filters["owner_team"] = owner_team
    if problem_manager: filters["problem_manager"] = problem_manager
    if q:               filters["subject"] = ["like", f"%{q}%"]

    fields = [
        "name", "subject", "status", "severity",
        "owner_team", "problem_manager",
        "first_seen_on", "mitigated_on", "resolved_on",
        "reopened_count", "modified",
    ]
    rows = frappe.get_all(
        "Problem Ticket",
        fields=fields,
        filters=filters,
        limit_start=start,
        limit_page_length=limit,
        order_by="modified desc",
    )
    return {"ok": True, "problems": rows}


@frappe.whitelist(allow_guest=True, methods=["POST", "PUT"])
def upsert_problem_ticket(
    name: str | None = None,
    fields: str | dict | None = None,
    lookup_by: str | None = None,
    preview: int | bool = 0,
    normalize_html: int | bool = 1,
    strict: int | bool = 1,
):
    data = _parse_fields_arg(fields)
    if not name and not data.get("subject"):
        frappe.throw("`subject` is required to create a Problem Ticket")

    if cint(strict):
        allowed = (
            PROBLEM_TEXT_FIELDS
            | set(PROBLEM_SELECT_FIELDS)
            | set(PROBLEM_LINK_FIELDS)
            | PROBLEM_DATETIME_FIELDS
            | PROBLEM_INT_FIELDS
        )
        extras = set(data.keys()) - allowed
        if extras:
            frappe.throw(f"Unknown fields: {sorted(extras)}")

    created = False

    if not name and lookup_by == "subject" and data.get("subject"):
        name = _find_problem_by_subject(cstr(data["subject"]).strip())

    if name:
        if not frappe.db.exists("Problem Ticket", name):
            frappe.throw(f"Problem Ticket not found: {name}")
        doc = frappe.get_doc("Problem Ticket", name)
    else:
        doc = frappe.new_doc("Problem Ticket")
        created = True

    changed: Dict[str, Any] = {}

    for k in PROBLEM_TEXT_FIELDS:
        if k in data:
            val = cstr(data.get(k))
            if k != "subject" and cint(normalize_html):
                val = _clean_html(val)
            if created or _changed(getattr(doc, k, None), val):
                setattr(doc, k, val)
                changed[k] = val

    for k, allowed in PROBLEM_SELECT_FIELDS.items():
        if k in data:
            v = cstr(data.get(k))
            if v and v not in allowed:
                frappe.throw(f"Invalid value for {k}. Allowed: {sorted(allowed)}")
            if created or _changed(getattr(doc, k, None), v):
                setattr(doc, k, v)
                changed[k] = v

    for k, dt in PROBLEM_LINK_FIELDS.items():
        if k in data:
            v = data.get(k)
            if v:
                if not frappe.db.exists(dt, v):
                    frappe.throw(f"Linked doc not found: {dt} {v}")
                if created or _changed(getattr(doc, k, None), v):
                    setattr(doc, k, v)
                    changed[k] = v
            else:
                if created or _changed(getattr(doc, k, None), None):
                    setattr(doc, k, None)
                    changed[k] = None

    for k in PROBLEM_DATETIME_FIELDS:
        if k in data:
            val = data.get(k)
            if created or _changed(getattr(doc, k, None), val):
                setattr(doc, k, val)
                changed[k] = val

    for k in PROBLEM_INT_FIELDS:
        if k in data:
            val = cint(data.get(k) or 0)
            if created or _changed(getattr(doc, k, None), val):
                setattr(doc, k, val)
                changed[k] = val

    no_change = (not created) and (len(changed) == 0)
    subject_for_log = cstr(data.get("subject") or getattr(doc, "subject", "")).strip()

    if cint(preview):
        try:
            ai_log_write(
                ticket=(data.get("primary_ticket") or ""),
                action="upsert_problem",
                status="WARN",
                source="ingest",
                preview=1,
                request=data,
                result={"created": created, "changed": changed, "no_change": no_change},
                subject=subject_for_log,
            )
        except Exception:
            pass
        return {"ok": True, "preview": True, "created": created, "changed": changed, "no_change": no_change}

    if created:
        doc.insert(ignore_permissions=True)
    elif changed:
        doc.save(ignore_permissions=True)
    frappe.db.commit()

    subject_for_log = cstr(getattr(doc, "subject", "") or data.get("subject") or "").strip()
    try:
        ai_log_write(
            ticket=(data.get("primary_ticket") or ""),
            action="upsert_problem",
            status="OK",
            source="ingest",
            preview=0,
            request=data,
            result={"name": doc.name, "created": created, "changed": changed, "no_change": no_change},
            subject=subject_for_log,
        )
    except Exception:
        pass

    return {"ok": True, "name": doc.name, "created": created, "changed": changed, "no_change": no_change}


@frappe.whitelist(allow_guest=True, methods=["POST", "PUT"])
def set_reply_suggestion(ticket: str, text: str, append: int | bool = 0, clean_html: int | bool = 1):
    return _apply_ticket_updates(
        ticket,
        {"ai_reply_suggestion": text},
        append=cint(append) == 1,
        clean_html=cint(clean_html) == 1,
    )


@frappe.whitelist(allow_guest=True, methods=["POST", "PUT"])
def set_sentiment(
    ticket: str,
    last_sentiment: str | None = None,
    sentiment_trend: str | None = None,
    effort_score: float | None = None,
    effort_band: str | None = None,
):
    updates: Dict[str, Any] = {}
    if last_sentiment is not None:
        updates["last_sentiment"] = last_sentiment
    if sentiment_trend is not None:
        updates["sentiment_trend"] = sentiment_trend
    if effort_score is not None:
        updates["effort_score"] = effort_score
    if effort_band is not None:
        updates["effort_band"] = effort_band
    return _apply_ticket_updates(ticket, updates)


@frappe.whitelist(allow_guest=True, methods=["POST", "PUT"])
def set_metrics(
    ticket: str,
    effort_score: float | None = None,
    cluster_hash: str | None = None,
):
    updates: Dict[str, Any] = {}

    if effort_score is not None:
        updates["effort_score"] = effort_score
    if cluster_hash is not None:
        updates["cluster_hash"] = cluster_hash
    return _apply_ticket_updates(ticket, updates)


@frappe.whitelist(allow_guest=True, methods=["POST", "PUT"])
def set_flags(ticket: str, shadow_mode: int | bool | None = None):
    updates: Dict[str, Any] = {}
    if shadow_mode is not None:
        updates["shadow_mode"] = 1 if cint(shadow_mode) else 0
    return _apply_ticket_updates(ticket, updates, respect_shadow=False)


# --- KB Update Requests ------------------------------------------------------
# DocType referanslı tam uyum + sade giriş (fields sarmalı opsiyonel)

_KB_DT = "Knowledge Base Update Request"


def _kb_meta():
    try:
        return frappe.get_meta(_KB_DT)
    except Exception:
        frappe.throw(f"Meta not found for {_KB_DT}")


def _kb_select_options(fieldname: str) -> set[str]:
    meta = _kb_meta()
    f = meta.get_field(fieldname)
    if not f:
        return set()
    opts = cstr(getattr(f, "options", "")).strip()
    return set([o.strip() for o in opts.split("\n") if o.strip()])  # HATA düzeltildi: doğru newline ayracı

_KB_ALLOWED_FIELDS_BASE = {
    "subject", "priority", "target_doctype", "target_name", "target_path",
    "tags", "current_summary", "proposed_changes", "references", "attachment", "breaking_change"
}


def _kb_allowed_fields() -> set[str]:
    meta = _kb_meta()
    return {f for f in _KB_ALLOWED_FIELDS_BASE if meta.has_field(f)}


def _kb_user() -> str:
    try:
        u = frappe.session.user or "Guest"
    except Exception:
        u = "Guest"
    return u


def _kb_resolve_attachment(val: str | None) -> str | None:
    if not val:
        return None
    s = cstr(val).strip()
    if not s:
        return None
    try:
        if frappe.db.exists("File", s):
            url = frappe.db.get_value("File", s, "file_url")
            return url or s
        row = frappe.db.get_value("File", {"file_name": s}, ["file_url"], as_dict=True)
        if row and row.get("file_url"):
            return row["file_url"]
    except Exception:
        pass
    return s


def _kb_default_series() -> str:
    try:
        meta = _kb_meta()
        f = meta.get_field("naming_series")
        default = cstr(getattr(f, "default", "")).strip() if f else ""
        return default or "KBUR-.YYYY.-.#####"
    except Exception:
        return "KBUR-.YYYY.-.#####"


def _kb_validate_options(change_type: str | None, priority: str | None):
    if change_type:
        allowed_ct = _kb_select_options("change_type")
        if allowed_ct and change_type not in allowed_ct:
            frappe.throw(f"Invalid `change_type`. Allowed: {sorted(allowed_ct)}")
    if priority:
        allowed_pr = _kb_select_options("priority")
        if allowed_pr and priority not in allowed_pr:
            frappe.throw(f"Invalid `priority`. Allowed: {sorted(allowed_pr)}")


def _kb_collect_payload(fields: str | dict | None) -> Dict[str, Any]:
    """İstemcinin gönderdiği gövdeden payload topla.
    Kabul edilen şekiller:
      - JSON body root'ta alanlar (subject, priority, ...)
      - JSON body {"fields": {...}}
      - x-www-form-urlencoded: fields=<json>
    """
    # 1) fields parametresi verilmişse
    data = _parse_fields_arg(fields)
    if data:
        return data

    # 2) JSON body
    req_json: Dict[str, Any] = {}
    try:
        req_json = frappe.request.get_json() or {}
    except Exception:
        try:
            req_json = frappe.request.json or {}
        except Exception:
            req_json = {}

    if isinstance(req_json, dict):
        if isinstance(req_json.get("fields"), dict):
            return req_json.get("fields")  # type: ignore
        allowed = _kb_allowed_fields()
        flat = {k: req_json.get(k) for k in allowed if k in req_json}
        if flat:
            return flat

    # 3) form_dict fallback
    try:
        fd = dict(frappe.form_dict)
        if "fields" in fd:
            try:
                return json.loads(fd.get("fields") or "{}")
            except Exception:
                return {}
        else:
            allowed = _kb_allowed_fields()
            flat = {k: fd.get(k) for k in allowed if k in fd}
            if flat:
                return flat
    except Exception:
        pass

    return {}


def _kb_clean_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    allowed = _kb_allowed_fields()
    out: Dict[str, Any] = {}
    for k in (data or {}):
        if k not in allowed:
            continue
        v = data.get(k)
        if k in {"current_summary", "proposed_changes", "references"}:
            out[k] = _clean_html(cstr(v))
        elif k == "breaking_change":
            out[k] = 1 if cint(v) else 0
        else:
            out[k] = cstr(v) if v is not None else None
    if "attachment" in allowed:
        out["attachment"] = _kb_resolve_attachment(out.get("attachment"))
    return out


def _kb_create_request(
    change_type: str,
    fields: str | dict | None = None,
) -> Dict[str, Any]:
    # TR: Sade akış — preview/strict parametreleri KALDIRILDI.
    payload_raw = _kb_collect_payload(fields)
    payload = _kb_clean_payload(payload_raw)

    subject = cstr(payload.get("subject") or "").strip()
    if not subject:
        frappe.throw("`subject` is required")

    _kb_validate_options(change_type, payload.get("priority"))

    created_doc = {
        "doctype": _KB_DT,
        "naming_series": _kb_default_series(),
        "subject": subject,
        "status": "Open",
        "change_type": change_type,
        "priority": payload.get("priority") or None,
        "requester": _kb_user(),
        "target_doctype": payload.get("target_doctype"),
        "target_name": payload.get("target_name"),
        "target_path": payload.get("target_path"),
        "tags": payload.get("tags"),
        "current_summary": payload.get("current_summary"),
        "proposed_changes": payload.get("proposed_changes"),
        "references": payload.get("references"),
        "attachment": payload.get("attachment"),
        "breaking_change": payload.get("breaking_change", 0),
    }

    doc = frappe.get_doc(created_doc)
    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    try:
        ai_log_write(
            ticket="",
            action="kb_update_request",
            status="OK",
            source="ingest",
            preview=0,
            request={"change_type": change_type, "fields": payload},
            result={"name": doc.name},
            subject=subject,
        )
    except Exception:
        pass

    return {"ok": True, "name": doc.name, "change_type": change_type}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def request_kb_new_article(fields: str | dict | None = None):
    return _kb_create_request("New Article", fields=fields)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def request_kb_fix(fields: str | dict | None = None):
    return _kb_create_request("Fix", fields=fields)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def request_kb_update(fields: str | dict | None = None):
    return _kb_create_request("Update", fields=fields)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def report_kb_wrong_document(fields: str | dict | None = None):
    return _kb_create_request("Deprecate", fields=fields)


# ---- Genel/Esnek uç nokta --------------------------------------------------

@frappe.whitelist(allow_guest=True, methods=["POST", "PUT"])
def update_ticket(
    ticket: str,
    fields: str | dict | None = None,
    append: int | bool = 0,
    clean_html: int | bool = 1,
    ignore_shadow: int | bool = 0,
):
    updates = _parse_fields_arg(fields)
    return _apply_ticket_updates(
        ticket,
        updates,
        append=cint(append) == 1,
        clean_html=cint(clean_html) == 1,
        respect_shadow=not bool(cint(ignore_shadow)),
    )


# ---- Shadow debug -----------------------------------------------------------

@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_shadow_status(ticket: str | None = None):
    st = _settings()
    g = bool(cint(getattr(st, "shadow_mode", 0))) if st else False
    t = False
    if ticket:
        try:
            t = bool(cint(frappe.db.get_value("HD Ticket", ticket, "shadow_mode") or 0))
        except Exception:
            t = False
    return {"ok": True, "global_shadow": g, "ticket_shadow": t, "effective": bool(g or t)}


# --- Basit yerel testler (framework bağımsız) -------------------------------

def _run_sanity_tests():
    # TEXT birleştirme
    assert _append_text("", "B", True) == "B"  # base boşsa sadece yeni metin
    assert _append_text("A", "B", True) == "A\nB"  # tek satır sonu ile ekleme
    assert _append_text("A", "B", False) == "B"  # append kapalıysa overwrite
    assert _append_text("A", "", True) == "A\n"  # yeni metin boşsa yine newline eklenir

    # options split davranışı
    opts = "Open\nApproved\nRejected"
    parsed = set([o.strip() for o in opts.split("\n") if o.strip()])
    assert parsed == {"Open", "Approved", "Rejected"}


if __name__ == "__main__":
    _run_sanity_tests()
