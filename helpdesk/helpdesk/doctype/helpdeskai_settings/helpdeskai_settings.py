# TR: HelpdeskAI Settings — doğrulama ve sınırlar (Yeni lisans mimarisi)
# -*- coding: utf-8 -*-
import frappe
from frappe.model.document import Document
from frappe.utils import cint

MAX_BILLING_GRACE_DAYS = 30  # TR: 0..30 arası önerilir

class HelpdeskAISettings(Document):
    def validate(self):
        # (1) Billing grace clamp: 0..30
        if hasattr(self, "billing_grace_days"):
            self.billing_grace_days = max(0, min(MAX_BILLING_GRACE_DAYS, cint(self.billing_grace_days or 0)))

        # (2) Last check default — boş ise UNKNOWN
        if not getattr(self, "last_check_status", None):
            self.last_check_status = "UNKNOWN"

        # (3) Salt alanı (opsiyonel) — boşsa dokunma; doluysa trimle
        if hasattr(self, "site_salt") and self.site_salt is not None:
            self.site_salt = (self.site_salt or "").strip()

        # (4) Read-only alanlar kullanıcı tarafından değiştirilmeye çalışılırsa geri al (UI güvenliği)
        ro_fields = ["device_fingerprint", "activation_token", "expires_at", "last_ok_on", "grace_until"]
        for f in ro_fields:
            # DB'deki değerle farklıysa, DB değerine geri çek
            try:
                db_val = frappe.db.get_single_value("HelpdeskAI Settings", f)
                cur_val = getattr(self, f, None)
                if db_val is not None and cur_val != db_val:
                    setattr(self, f, db_val)
            except Exception:
                # Alan yoksa sessizce geç
                pass
