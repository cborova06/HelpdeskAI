# -*- coding: utf-8 -*-
# TR: HelpdeskAI Lisans Mekanizması Ünite Testleri
import json
from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime, add_days

# TR: Test edilecek modül
from helpdesk.api import license as license_api


class TestLicenseAPI(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")

        # TR: Settings'i sıfırla
        st = frappe.get_single("HelpdeskAI Settings")
        st.license_key = "TEST-KEY-XXXX-1234"
        st.instance_id = ""              # TR: otomatik üretim test edilecek
        st.expires_at = None
        st.offline_grace_minutes = 0
        st.activation_url = "https://brvsoftware.com/wp-json/brv-slm/v1/activate-license"
        st.deactivation_url = "https://brvsoftware.com/wp-json/brv-slm/v1/deactivate-license"
        st.verification_url = "https://brvsoftware.com/wp-json/brv-slm/v1/verify-license"
        # TR: alan mevcutsa 30 olarak yaz; yoksa kod 30 varsayıyor
        try:
            st.billing_grace_days = 30
        except Exception:
            pass
        st.save(ignore_permissions=True)

        # TR: Cache temizle
        frappe.cache().delete_value(license_api.CACHE_STATUS_KEY)
        frappe.cache().delete_value(license_api.CACHE_LAST_CHECK)

        # TR: Audit temiz (test karşılaştırmaları için)
        frappe.db.delete("License Audit Log")

    # ---- Yardımcılar --------------------------------------------------------

    class DummyResp:
        def __init__(self, url, json_data, ok=True, status_code=200):
            self.url = url
            self._json = json_data
            self.ok = ok
            self.status_code = status_code
            self.content = json.dumps(json_data).encode()

        def json(self):
            return self._json

    # ---- Aktivasyon ---------------------------------------------------------

    @patch("helpdesk.api.license.requests.post")
    def test_activate_success_updates_settings_cache_and_audit(self, post):
        # TR: Sunucu başarı döndürür + expires_at verir
        data = {"success": True, "license_status": "active", "expires_at": (now_datetime() + timedelta(days=365)).isoformat()}
        post.return_value = self.DummyResp(
            "https://brvsoftware.com/wp-json/brv-slm/v1/activate-license", data, ok=True, status_code=200
        )

        res = license_api.activate()
        self.assertTrue(res.get("ok"))
        self.assertEqual(frappe.cache().get_value(license_api.CACHE_STATUS_KEY), "valid")

        # TR: expires_at settings'e yazılmış olmalı
        st = frappe.get_single("HelpdeskAI Settings")
        self.assertTrue(st.expires_at)

        # TR: instance_id otomatik üretilmiş olmalı
        self.assertTrue(st.instance_id)

        # TR: Audit kaydı yazılmış olmalı
        self.assertGreater(frappe.db.count("License Audit Log"), 0)

    @patch("helpdesk.api.license.requests.post")
    def test_activate_failure_sets_invalid_and_audit(self, post):
        data = {"success": False, "status": "error"}
        post.return_value = self.DummyResp(
            "https://brvsoftware.com/wp-json/brv-slm/v1/activate-license", data, ok=True, status_code=200
        )

        res = license_api.activate()
        self.assertFalse(res.get("ok"))
        self.assertEqual(frappe.cache().get_value(license_api.CACHE_STATUS_KEY), "invalid")
        self.assertGreater(frappe.db.count("License Audit Log"), 0)

    # ---- Deaktivasyon -------------------------------------------------------

    @patch("helpdesk.api.license.requests.post")
    def test_deactivate_success_sets_invalid_and_audit(self, post):
        data = {"success": True, "status": "deactivated"}
        post.return_value = self.DummyResp(
            "https://brvsoftware.com/wp-json/brv-slm/v1/deactivate-license", data, ok=True, status_code=200
        )

        res = license_api.deactivate()
        self.assertTrue(res.get("ok"))
        self.assertEqual(frappe.cache().get_value(license_api.CACHE_STATUS_KEY), "invalid")
        self.assertGreater(frappe.db.count("License Audit Log"), 0)

    # ---- Doğrulama: geçerli -------------------------------------------------

    @patch("helpdesk.api.license.requests.post")
    def test_verify_valid_sets_cache_valid(self, post):
        data = {"valid": True, "license_status": "active"}
        post.return_value = self.DummyResp(
            "https://brvsoftware.com/wp-json/brv-slm/v1/verify-license", data, ok=True, status_code=200
        )

        res = license_api.verify()
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("status"), "valid")
        self.assertEqual(frappe.cache().get_value(license_api.CACHE_STATUS_KEY), "valid")

    # ---- Doğrulama: grace (30 gün) -----------------------------------------

    @patch("helpdesk.api.license.requests.post")
    def test_verify_grace_within_30_days_ok(self, post):
        # TR: Sunucu 'active' döndürmüyor ama expiry geçmiş + 30g içinde
        expired = now_datetime() - timedelta(days=5)
        data = {"success": False, "status": "expired", "expires_at": expired.isoformat()}
        post.return_value = self.DummyResp(
            "https://brvsoftware.com/wp-json/brv-slm/v1/verify-license", data, ok=True, status_code=200
        )

        res = license_api.verify()
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("status"), "grace")
        self.assertEqual(frappe.cache().get_value(license_api.CACHE_STATUS_KEY), "grace")

    # ---- Doğrulama: revoked -> invalid -------------------------------------

    @patch("helpdesk.api.license.requests.post")
    def test_verify_revoked_is_invalid(self, post):
        data = {"success": False, "status": "revoked"}
        post.return_value = self.DummyResp(
            "https://brvsoftware.com/wp-json/brv-slm/v1/verify-license", data, ok=True, status_code=200
        )

        res = license_api.verify()
        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("status"), "invalid")
        self.assertEqual(frappe.cache().get_value(license_api.CACHE_STATUS_KEY), "invalid")

    # ---- Doğrulama: network error + yerel grace -----------------------------

    @patch("helpdesk.api.license.requests.post", side_effect=Exception("network down"))
    def test_verify_network_error_uses_local_grace(self, post):
        # TR: Settings'e yerel expiry yaz, 30g içinde olsun
        st = frappe.get_single("HelpdeskAI Settings")
        st.expires_at = add_days(now_datetime(), -2)  # TR: 2 gün önce bitti
        try:
            st.billing_grace_days = 30
        except Exception:
            pass
        st.save(ignore_permissions=True)

        res = license_api.verify()
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("status"), "grace")

    # ---- Gatekeeper ---------------------------------------------------------

    def test_gatekeeper_ok_when_valid_or_grace(self):
        # TR: cache 'valid'
        frappe.cache().set_value(license_api.CACHE_STATUS_KEY, "valid")
        frappe.cache().set_value(license_api.CACHE_LAST_CHECK, int(now_datetime().timestamp()))
        res = license_api.gatekeeper()
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("status"), "valid")

        # TR: cache 'grace'
        frappe.cache().set_value(license_api.CACHE_STATUS_KEY, "grace")
        frappe.cache().set_value(license_api.CACHE_LAST_CHECK, int(now_datetime().timestamp()))
        res2 = license_api.gatekeeper()
        self.assertTrue(res2.get("ok"))
        self.assertEqual(res2.get("status"), "grace")

    # ---- Domain zorlaması ---------------------------------------------------

    @patch("helpdesk.api.license.requests.post")
    def test_domain_enforced_only_brvsoftware(self, post):
        # TR: Artık URL'ler sabit; sabiti kötü domaine çevir ve PermissionError bekle
        import helpdesk.api.license as lic
        lic.DEFAULT_ACTIVATE_URL = "https://evil.example.com/api/activate"

        with self.assertRaises(frappe.PermissionError):
            license_api.activate()

        # TR: Domain kontrolü post’tan önce patladığı için HTTP çağrısı olmamalı
        post.assert_not_called()
