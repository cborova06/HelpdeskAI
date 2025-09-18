# -*- coding: utf-8 -*-
from __future__ import annotations
from urllib.parse import urlparse
import threading

import requests
import frappe

from . import license as license_api

# Yalnız lisans sunucusuna her zaman izin ver
ALLOWED_NETLOCS = {"brvsoftware.com"}

# Kurulum durumu
_guard_lock = threading.Lock()
_installed = False
_orig_request = None


def _license_ok() -> bool:
    """Cache'den hızlı kontrol; yoksa hafif verify (ayar yazmaz)."""
    try:
        status = (frappe.cache().get_value(license_api.CACHE_STATUS_KEY) or "unknown").lower()
    except Exception:
        status = "unknown"

    if status in ("valid", "grace"):
        return True

    try:
        res = license_api.verify(update_settings=0)
        return (res or {}).get("status") in ("valid", "grace")
    except Exception:
        return False


def install_global_http_guard() -> None:
    """
    requests.sessions.Session.request seviyesinde global HTTP koruması.
    Webhook'lar dahil tüm outbound HTTP çağrıları buradan geçer.
    """
    global _installed, _orig_request
    with _guard_lock:
        if _installed:
            return

        _orig_request = requests.sessions.Session.request

        def guarded_request(self, method, url, *args, **kwargs):
            netloc = ""
            try:
                netloc = urlparse(url or "").netloc.lower()
            except Exception:
                pass

            # Lisans sunucusuna her zaman izin ver
            allow = netloc.endswith("brvsoftware.com")

            # Lisans geçerli/grace değilse engelle
            if not allow and not _license_ok():
                try:
                    frappe.logger("helpdesk.license").warning(f"HTTP blocked by license: {method} {url}")
                except Exception:
                    pass
                raise frappe.PermissionError("HTTP call blocked by HelpdeskAI license policy.")

            return _orig_request(self, method, url, *args, **kwargs)

        requests.sessions.Session.request = guarded_request
        _installed = True


def uninstall_global_http_guard() -> None:
    """Testlerde/devre dışı bırakmada kullanmak için geri alma."""
    global _installed, _orig_request
    with _guard_lock:
        if not _installed:
            return
        if _orig_request:
            requests.sessions.Session.request = _orig_request
        _orig_request = None
        _installed = False
