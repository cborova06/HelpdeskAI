# TR: HelpdeskAI Settings — doğrulama ve sınırlar
# -*- coding: utf-8 -*-
import frappe
from frappe.model.document import Document
from frappe.utils import cint


MAX_BILLING_GRACE_DAYS = 30
MAX_OFFLINE_GRACE_MIN = 1440 # 24 saat


# helpdesk/helpdesk/doctype/helpdeskai_settings/helpdeskai_settings.py

class HelpdeskAISettings(Document):
    def validate(self):
        # (1) Billing grace clamp: 0..30  — TR: Kullanıcı ne girerse girsin bu aralığa çek
        if hasattr(self, "billing_grace_days"):
            self.billing_grace_days = max(0, min(MAX_BILLING_GRACE_DAYS, cint(self.billing_grace_days or 0)))

        # (2) Offline grace clamp: 0..1440 — TR: 24 saati geçmesin
        if hasattr(self, "offline_grace_minutes"):
            self.offline_grace_minutes = max(0, min(MAX_OFFLINE_GRACE_MIN, cint(self.offline_grace_minutes or 0)))

        # (3) Last check default — TR: Boş ise UNKNOWN yap
        if not getattr(self, "last_check_status", None):
            self.last_check_status = "UNKNOWN"

        # (4) Grace kilidi aktifken UI değişikliğini geri al
        #     TR: UnboundLocalError için db_val'ı her durumda güvenle tanımla
        grace_locked = cint(getattr(self, "grace_locked_days", 0) or 0)   # TR: Kilit var mı?
        if grace_locked > 0:
            db_val = frappe.db.get_single_value("HelpdeskAI Settings", "billing_grace_days")  # TR: DB'deki asıl değer
            if db_val is not None and cint(self.billing_grace_days) != cint(db_val):
                self.billing_grace_days = cint(db_val)  # TR: Kullanıcının değişikliğini geri al
                frappe.msgprint("Grace aktifken 'Billing Grace (days)' değiştirilemez.")  # TR: Bilgilendirme
