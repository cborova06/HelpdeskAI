# -*- coding: utf-8 -*-
# TR: HelpdeskAI Settings — Ünite Testleri
import json
from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime, add_days

# TR: Lisans API modülü
from helpdesk.api import license as license_api


class TestHelpdeskAISettings(FrappeTestCase):
    # TR: Yardımcı HTTP yanıtı (domain denetimi için gerçek URL gerekir)
    class DummyResp:
        def __init__(self, url, json_data, ok=True, status_code=200):
            self.url = url
            self._json = json_data
            self.ok = ok
            self.status_code = status_code
            self.content = json.dumps(json_data).encode()
        def json(self):
            return self._json

    def setUp(self):
        frappe.set_user("Administrator")  # TR: Yönetici ile çalış
        self.st = frappe.get_single("HelpdeskAI Settings")  # TR: Single DocType
        # TR: Varsayılan alanları sıfırla
        self.st.license_key = "TEST-KEY-XXXX-1234"
        self.st.instance_id = ""
        self.st.expires_at = None
        try:
            self.st.billing_grace_days = 30
        except Exception:
            pass
        self.st.offline_grace_minutes = 0
        self.st.last_check_on = None
        self.st.last_check_status = None
        self.st.save(ignore_permissions=True)
        # TR: Cache ve Audit temizliği
        frappe.cache().delete_value(license_api.CACHE_STATUS_KEY)
        frappe.cache().delete_value(license_api.CACHE_LAST_CHECK)
        frappe.db.delete("License Audit Log")

    # ---- Meta / Yapı testleri ---------------------------------------------

    def test_meta_contains_expected_fields_and_types(self):
        meta = frappe.get_meta("HelpdeskAI Settings")
        # TR: Single olmalı
        self.assertTrue(meta.issingle)
        # TR: URL alanları artık olmamalı
        self.assertFalse(meta.has_field("activation_url"))
        self.assertFalse(meta.has_field("deactivation_url"))
        self.assertFalse(meta.has_field("verification_url"))
        # TR: yeni RO alanlar bulunmalı
        self.assertTrue(meta.has_field("last_check_on"))
        self.assertTrue(meta.has_field("last_check_status"))
        # TR: license_key Password olmalı
        f = meta.get_field("license_key")
        self.assertEqual(f.fieldtype, "Password")

    # ---- validate() sınırları ---------------------------------------------

    def test_billing_grace_days_clamped_between_0_and_30(self):
        self.st.billing_grace_days = -5
        self.st.save(ignore_permissions=True)
        self.assertEqual(self.st.billing_grace_days, 0)  # TR: alt sınır
        self.st.billing_grace_days = 999
        self.st.save(ignore_permissions=True)
        self.assertEqual(self.st.billing_grace_days, 30)  # TR: üst sınır

    def test_offline_grace_minutes_clamped(self):
        self.st.offline_grace_minutes = -10
        self.st.save(ignore_permissions=True)
        self.assertEqual(self.st.offline_grace_minutes, 0)
        self.st.offline_grace_minutes = 99999
        self.st.save(ignore_permissions=True)
        self.assertEqual(self.st.offline_grace_minutes, 1440)

    def test_last_check_status_defaults_unknown(self):
        self.st.last_check_status = None
        self.st.save(ignore_permissions=True)
        self.assertEqual(self.st.last_check_status, "UNKNOWN")

    # ---- verify() ile entegrasyon -----------------------------------------

    @patch("helpdesk.api.license.requests.post")
    def test_verify_updates_last_check_fields_valid(self, post):
        data = {"valid": True, "license_status": "active", "expires_at": (now_datetime() + timedelta(days=365)).isoformat()}
        post.return_value = self.DummyResp("https://brvsoftware.com/wp-json/brv-slm/v1/verify-license", data, ok=True)

        res = license_api.verify()
        self.assertTrue(res.get("ok"))
        st = frappe.get_single("HelpdeskAI Settings").reload()
        self.assertEqual(st.last_check_status, "VALID")
        self.assertIsNotNone(st.last_check_on)

    @patch("helpdesk.api.license.requests.post")
    def test_verify_sets_grace_when_expired_within_30_days(self, post):
        expired = now_datetime() - timedelta(days=3)
        data = {"success": False, "status": "expired", "expires_at": expired.isoformat()}
        post.return_value = self.DummyResp("https://brvsoftware.com/wp-json/brv-slm/v1/verify-license", data, ok=True)

        res = license_api.verify()
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("status"), "grace")
        st = frappe.get_single("HelpdeskAI Settings").reload()
        self.assertEqual(st.last_check_status, "GRACE")

    @patch("helpdesk.api.license.requests.post", side_effect=Exception("net down"))
    def test_verify_network_error_falls_back_to_local_grace(self, post):
        # TR: Yerel expiry 2 gün önce — grace penceresinde
        self.st.expires_at = add_days(now_datetime(), -2)
        self.st.save(ignore_permissions=True)

        res = license_api.verify()
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("status"), "grace")
        st = frappe.get_single("HelpdeskAI Settings").reload()
        self.assertEqual(st.last_check_status, "GRACE")