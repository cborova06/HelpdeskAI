# /home/frappe/frappe-bench/apps/helpdesk/helpdesk/api/ai_log.py

from __future__ import annotations
from typing import Any, Dict, List
import frappe
from frappe.utils import now_datetime, cint

def _safe_get_ticket_subject(ticket: str | None) -> str:
    """# TR: HD Ticket başlığını güvenli biçimde al (yoksa boş döner)."""
    if not ticket:
        return ""
    try:
        # TR: En yaygın alan adı "subject"
        return (frappe.db.get_value("HD Ticket", ticket, "subject") or "").strip()
    except Exception:
        return ""

def _summarize_updates(request: Dict[str, Any] | None, result: Dict[str, Any] | None) -> str:
    """# TR: Güncellenen alanları kısa özet olarak üret (subject’e eklenecek)."""
    keys: List[str] = []
    try:
        if isinstance(request, dict):
            keys.extend([k for k in request.keys()])
        if isinstance(result, dict):
            # TR: changed/preview anahtarları altında gelen alanları da ekle
            for k in ("changed", "preview"):
                if isinstance(result.get(k), dict):
                    keys.extend(list(result[k].keys()))
    except Exception:
        pass
    keys = sorted(set(keys))
    if not keys:
        return ""
    if len(keys) > 4:
        return f"fields: {', '.join(keys[:4])}…"
    return f"fields: {', '.join(keys)}"

def _compose_subject(
    *,
    ticket: str,
    action: str,
    status: str,
    source: str | None,
    direction: str | None,
    preview_flag: int | bool,
    request: Dict[str, Any] | None,
    result: Dict[str, Any] | None,
) -> str:
    """# TR: Anlamlı ve tutarlı subject oluşturur."""
    ticket_subject = _safe_get_ticket_subject(ticket)
    parts = []  # TR: Subject parçaları

    # TR: [Status] [Source/Direction]
    parts.append(f"[{(status or 'OK').upper()}]")
    if source:
        if direction:
            parts.append(f"[{source}/{direction}]")
        else:
            parts.append(f"[{source}]")

    # TR: İşlem + Ticket No
    parts.append(f"{action} — T#{ticket}")

    # TR: İsteğe bağlı ticket başlığı
    if ticket_subject:
        parts.append(f"— {ticket_subject}")

    # TR: Güncellenen alanlar özeti
    upd = _summarize_updates(request, result)
    if upd:
        parts.append(f"({upd})")

    # TR: Shadow/Preview vurgusu
    if cint(preview_flag):
        parts.append("(preview)")

    # TR: Boş kalmasın diye garanti
    subject = " ".join([p for p in parts if p]).strip()
    if not subject:
        subject = f"{action} — {ticket}"
    return subject[:140]  # TR: Aşırı uzamayı kes

def write(
    ticket: str,
    action: str,
    *,
    status: str = "OK",
    source: str = "ingest",
    preview: int | bool = 0,
    request: Dict[str, Any] | None = None,
    result: Dict[str, Any] | None = None,
    meta: Dict[str, Any] | None = None,
    subject: str | None = None,              # NEW: isteğe bağlı subject
    direction: str | None = None,            # NEW: isteğe bağlı direction
):
    try:
        doc = frappe.new_doc("AI Interaction Log")
        doc.ticket = ticket
        doc.action = action
        doc.status = status
        doc.source = source
        doc.preview = 1 if cint(preview) else 0

        # TR: Subject — verilen değeri kullan; yoksa akıllı oluşturucu
        doc.subject = (subject or "").strip() or _compose_subject(
            ticket=ticket,
            action=action,
            status=status,
            source=source,
            direction=direction,
            preview_flag=doc.preview,
            request=request,
            result=result,
        )

        # TR: Direction — sonuç varsa Response, yoksa Request (manuel değer öncelikli)
        if direction:
            doc.direction = direction
        else:
            try:
                has_result = bool(result) and (len(result) > 0)
            except Exception:
                has_result = False
            doc.direction = "Response" if has_result else "Request"

        doc.request_json = frappe.as_json(request or {})
        doc.result_json  = frappe.as_json(result  or {})
        if meta:
            doc.meta_json = frappe.as_json(meta)

        doc.event_ts = now_datetime()
        doc.user = getattr(frappe.session, "user", None)

        # TR: İstemci IP (varsa)
        try:
            doc.ip_address = getattr(frappe.local, "request_ip", None)
        except Exception:
            pass

        doc.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(f"ai_log.write: {e}", "HelpdeskAI")
