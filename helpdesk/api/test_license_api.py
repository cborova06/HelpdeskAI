# -*- coding: utf-8 -*-
# TR: HelpdeskAI Yeni Lisans Mekanizması Ünite Testleri (activate / validate / deactivate + grace)
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
        frappe.set_user("Administrator")  # TR: Test kullanıcısı

        # TR: Settings'i deterministik hale getir
        st = frappe.get_single("HelpdeskAI Settings")  # TR: Single settings
        st.license_key = "TEST-KEY-XXXX-1234"  # TR: Sahte lisans
        st.device_fingerprint = ""  # TR: İlk çağrıda üretilecek
        st.activation_token = None  # TR: Aktivasyon sonrası dolacak
        st.last_ok_on = None  # TR: Grace referansı
        st.expires_at = None  # TR: Opsiyonel sunucu alanı
        # TR: Alan mevcutsa 30 gün olarak set edilir; yoksa kod 30 varsayıyor
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
            self.url = url  # TR: requests.Response.url
            self._json = json_data  # TR: Dönen JSON
            self.ok = ok  # TR: HTTP 2xx mı
            self.status_code = status_code  # TR: HTTP kodu
            self.content = json.dumps(json_data).encode()  # TR: bytes içerik

        def json(self):
            return self._json  # TR: JSON accessor

    # ---- Aktivasyon ---------------------------------------------------------

    @patch("helpdesk.api.license.requests.post")
    def test_activate_success_updates_settings_cache_and_audit(self, post):
        # TR: Sunucu başarı + activation_token + exp döner
        data = {
            "ok": True,  # TR: yeni API: ok
            "status": "active",  # TR: durum
            "activation_token": "TOK-123",  # TR: saklanacak token
            "exp": (now_datetime() + timedelta(days=365)).isoformat(),  # TR: opsiyonel son kullanma
        }
        post.return_value = self.DummyResp(
            "https://brvsoftware.com/wp-json/lic/v1/activate", data, ok=True, status_code=200
        )

        res = license_api.activate()  # TR: çağrı
        self.assertTrue(res.get("ok"))  # TR: başarılı
        self.assertEqual(frappe.cache().get_value(license_api.CACHE_STATUS_KEY), "valid")  # TR: cache valid

        st = frappe.get_single("HelpdeskAI Settings")  # TR: güncel settings
        self.assertTrue(st.activation_token)  # TR: token yazıldı
        self.assertTrue(st.device_fingerprint)  # TR: fingerprint üretildi
        self.assertEqual(len(st.device_fingerprint), 64)  # TR: SHA256 hex
        self.assertGreater(frappe.db.count("License Audit Log"), 0)  # TR: audit yazıldı

    @patch("helpdesk.api.license.requests.post")
    def test_activate_failure_sets_invalid_and_audit(self, post):
        data = {"ok": False, "error": "invalid_key"}  # TR: yeni API hata formatı
        post.return_value = self.DummyResp(
            "https://brvsoftware.com/wp-json/lic/v1/activate", data, ok=True, status_code=200
        )

        res = license_api.activate()  # TR: çağrı
        self.assertFalse(res.get("ok"))  # TR: başarısız
        self.assertEqual(frappe.cache().get_value(license_api.CACHE_STATUS_KEY), "invalid")  # TR: cache invalid
        self.assertGreater(frappe.db.count("License Audit Log"), 0)  # TR: audit yazıldı

    # ---- Deaktivasyon -------------------------------------------------------

    @patch("helpdesk.api.license.requests.post")
    def test_deactivate_success_sets_invalid_and_audit(self, post):
        # TR: Ön şart: token varmış gibi davran
        st = frappe.get_single("HelpdeskAI Settings")
        st.activation_token = "TOK-XYZ"
        st.save(ignore_permissions=True)

        data = {"ok": True, "status": "deactivated"}  # TR: yeni API
        post.return_value = self.DummyResp(
            "https://brvsoftware.com/wp-json/lic/v1/deactivate", data, ok=True, status_code=200
        )

        res = license_api.deactivate()  # TR: çağrı
        self.assertTrue(res.get("ok"))  # TR: başarılı
        self.assertEqual(frappe.cache().get_value(license_api.CACHE_STATUS_KEY), "invalid")  # TR: cache invalid

        st = frappe.get_single("HelpdeskAI Settings")  # TR: settings kontrol
        self.assertFalse(st.activation_token)  # TR: token temizlendi
        self.assertGreater(frappe.db.count("License Audit Log"), 0)  # TR: audit yazıldı

    # ---- Doğrulama: geçerli -------------------------------------------------

    @patch("helpdesk.api.license.requests.post")
    def test_validate_valid_sets_cache_valid_and_updates_last_ok(self, post):
        data = {"ok": True, "status": "active", "exp": (now_datetime() + timedelta(days=90)).isoformat()}
        post.return_value = self.DummyResp(
            "https://brvsoftware.com/wp-json/lic/v1/validate", data, ok=True, status_code=200
        )

        res = license_api.validate()  # TR: çağrı
        self.assertTrue(res.get("ok"))  # TR: başarılı
        self.assertEqual(res.get("status"), "valid")  # TR: durum valid
        self.assertEqual(frappe.cache().get_value(license_api.CACHE_STATUS_KEY), "valid")  # TR: cache valid

        st = frappe.get_single("HelpdeskAI Settings")
        self.assertIsNotNone(st.last_ok_on)  # TR: grace referansı güncellendi

    # ---- Doğrulama: invalid -------------------------------------------------

    @patch("helpdesk.api.license.requests.post")
    def test_validate_invalid_sets_cache_invalid(self, post):
        data = {"ok": False, "error": "expired"}  # TR: yeni API invalid
        post.return_value = self.DummyResp(
            "https://brvsoftware.com/wp-json/lic/v1/validate", data, ok=True, status_code=200
        )

        res = license_api.validate()  # TR: çağrı
        self.assertFalse(res.get("ok"))  # TR: başarısız
        self.assertEqual(res.get("status"), "expired")  # TR: hata mesajı geri döner
        self.assertEqual(frappe.cache().get_value(license_api.CACHE_STATUS_KEY), "invalid")  # TR: cache invalid

    # ---- Doğrulama: revoked -> invalid -------------------------------------

    @patch("helpdesk.api.license.requests.post")
    def test_validate_revoked_is_invalid(self, post):
        data = {"ok": False, "status": "revoked"}  # TR: revoke
        post.return_value = self.DummyResp(
            "https://brvsoftware.com/wp-json/lic/v1/validate", data, ok=True, status_code=200
        )

        res = license_api.validate()  # TR: çağrı
        self.assertFalse(res.get("ok"))  # TR: başarısız
        self.assertEqual(res.get("status"), "invalid")  # TR: invalid
        self.assertEqual(frappe.cache().get_value(license_api.CACHE_STATUS_KEY), "invalid")  # TR: cache invalid

    # ---- Doğrulama: network error + grace (last_ok_on + 30g) ---------------

    @patch("helpdesk.api.license.requests.post", side_effect=Exception("network down"))
    def test_validate_network_error_uses_last_ok_grace(self, post):
        # TR: Settings'e last_ok_on yaz, 30 gün içinde olsun
        st = frappe.get_single("HelpdeskAI Settings")
        st.last_ok_on = add_days(now_datetime(), -5)  # TR: 5 gün önce başarı görmüş
        try:
            st.billing_grace_days = 30
        except Exception:
            pass
        st.save(ignore_permissions=True)

        res = license_api.validate()  # TR: çağrı
        self.assertTrue(res.get("ok"))  # TR: grace kabul
        self.assertEqual(res.get("status"), "grace")  # TR: durum grace
        self.assertEqual(frappe.cache().get_value(license_api.CACHE_STATUS_KEY), "grace")  # TR: cache grace

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
        # TR: Sabiti kötü domaine çevir ve PermissionError bekle
        import helpdesk.api.license as lic
        lic.DEFAULT_ACTIVATE_URL = "https://evil.example.com/api/activate"

        with self.assertRaises(frappe.PermissionError):
            license_api.activate()  # TR: domain kontrolü post öncesi patlamalı

        post.assert_not_called()  # TR: HTTP çağrısı olmamalı
