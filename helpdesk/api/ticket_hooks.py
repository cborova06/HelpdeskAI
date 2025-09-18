# -*- coding: utf-8 -*-
# TR: Bilet oluşturulurken lisans durumunu al ve alanı doldur.
from __future__ import annotations
from helpdesk.api.license import gatekeeper

def before_insert_set_license_flag(doc, method=None):
    # TR: VALID/GRACE -> 1, aksi 0
    ok = bool(gatekeeper().get("ok"))
    doc.license_gate_ok = 1 if ok else 0
