from __future__ import annotations
import frappe

def _is_integration_bot(user: str | None = None) -> bool:
    # L5–L11: v5 uyumlu rol kontrolü (DB üzerinden)
    user = user or frappe.session.user
    if not user or user == "Guest":
        return False
    return frappe.db.exists(
        "Has Role", {"parent": user, "role": "Integration Bot", "parenttype": "User"}
    ) is not None

def _import_core_module():
    # L13–L25: Çekirdek Communication modülünü çok-sürümlü içe aktar
    core = None
    try:
        import frappe.core.doctype.communication.communication as core  # yeni yol
    except Exception:
        try:
            import frappe.email.doctype.communication.communication as core  # eski yol
        except Exception:
            core = None
    return core

_PATCHED = False
def _ensure_core_patched():
    # L31–L79: Çekirdek PQC/has_permission fonksiyonlarını Integration Bot için yumuşat
    global _PATCHED
    if _PATCHED:
        return
    core = _import_core_module()
    if not core:
        return
    orig_pqc = getattr(core, "get_permission_query_conditions_for_communication",
                       getattr(core, "get_permission_query_conditions", None))
    orig_has = getattr(core, "has_permission", None)

    def patched_pqc(user: str | None = None):
        # L46–L53: Integration Bot için kısıt yok
        if _is_integration_bot(user):
            return "1=1"
        return orig_pqc(user) if callable(orig_pqc) else None

    def patched_has(doc, ptype: str, user: str | None = None):
        # L56–L64: Integration Bot'a read/report/export/select serbest
        if _is_integration_bot(user) and ptype in {"read", "report", "export", "select"}:
            return True
        return orig_has(doc, ptype, user) if callable(orig_has) else False

    if hasattr(core, "get_permission_query_conditions_for_communication"):
        core.get_permission_query_conditions_for_communication = patched_pqc
    if hasattr(core, "get_permission_query_conditions"):
        core.get_permission_query_conditions = patched_pqc
    if hasattr(core, "has_permission"):
        core.has_permission = patched_has

    _PATCHED = True

# 🔴 KRİTİK: Modül import edilir edilmez patch'i uygula
_ensure_core_patched()  # L81: REST'te core PQC çağrılmadan önce patch aktif olur

def get_permission_query_conditions(user: str | None = None) -> str | None:
    # L85–L101: Bizim PQC; Integration Bot için yine 1=1
    if _is_integration_bot(user):
        return "1=1"
        # Sıkılaştırmak istersen:
        # return "coalesce(`tabCommunication`.`reference_doctype`, '')='HD Ticket'"
    core = _import_core_module()
    if core and hasattr(core, "get_permission_query_conditions_for_communication"):
        return core.get_permission_query_conditions_for_communication(user)
    if core and hasattr(core, "get_permission_query_conditions"):
        return core.get_permission_query_conditions(user)
    return None

def has_permission(doc, ptype: str, user: str | None = None) -> bool:
    # L103–L115: Tekil erişim
    if _is_integration_bot(user) and ptype in {"read", "report", "export", "select"}:
        return True
    core = _import_core_module()
    if core and hasattr(core, "has_permission"):
        return core.has_permission(doc, ptype, user)
    return False
