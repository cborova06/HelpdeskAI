# -*- coding: utf-8 -*-
"""
helpdesk.api.test_ingest

FrappeTestCase tabanlı kapsamlı birim testleri.
- GET uç noktaları: get_teams, get_team_members, get_tickets_by_team, get_tickets_by_user,
  get_articles, get_ticket (partial), get_routing_context, get_shadow_status
- POST/PUT uç noktaları: ingest_summary, set_reply_suggestion, set_sentiment,
  set_metrics, set_flags, update_ticket (whitelist/append/clean_html/shadow override)
- KB Update Requests: request_kb_new_article, request_kb_fix, request_kb_update, report_kb_wrong_document
- Problem Ticket: upsert(create/update/preview/strict), list_problem_tickets, get_problem_ticket

Çalıştırma:
  bench --site helpdeskai.localhost run-tests --module helpdesk.api.test_ingest
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Tuple

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cstr


# ----------------------------- Yardımcılar -----------------------------

def _ensure_team_and_member() -> Tuple[str, str]:
    """Minimal takım + üye üretimi."""
    team = "Product Experts"
    if not frappe.db.exists("HD Team", team):
        t = frappe.new_doc("HD Team")
        t.team_name = team
        t.insert(ignore_permissions=True)
    user = "Administrator"
    if frappe.db.table_exists("HD Team Member"):
        exists = frappe.db.get_all(
            "HD Team Member",
            filters={"parent": team, "parenttype": "HD Team", "user": user},
            pluck="name",
            limit=1,
        )
        if not exists:
            row = frappe.new_doc("HD Team Member")
            row.parent = team
            row.parenttype = "HD Team"
            row.parentfield = "members"
            row.user = user
            row.insert(ignore_permissions=True)
    return team, user


def _new_ticket(subject_prefix: str = "API Test") -> str:
    team, _ = _ensure_team_and_member()
    doc = frappe.new_doc("HD Ticket")
    doc.subject = f"{subject_prefix} – {uuid.uuid4().hex[:8]}"
    doc.description = "Created by helpdesk.api.test_ingest"
    doc.agent_group = team
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return cstr(doc.name)


# ----------------------------- Testler -----------------------------

class TestGetEndpoints(FrappeTestCase):
    def test_get_teams_and_members(self):
        team, user = _ensure_team_and_member()
        res = frappe.call("helpdesk.api.ingest.get_teams", include_members=1, include_tags=1)
        self.assertTrue(res.get("ok"))
        teams = res.get("teams") or []
        self.assertTrue(any(t.get("name") == team for t in teams))
        found = next(t for t in teams if t.get("name") == team)
        self.assertIn("members", found)
        self.assertIn(user, found.get("members", []))

    def test_get_ticket_partial_fields_and_shadow_flag(self):
        t = _new_ticket("Partial Fields")
        want = ["name", "subject", "ai_summary"]
        res = frappe.call("helpdesk.api.ingest.get_ticket", ticket=t, fields=json.dumps(want))
        tk = res.get("ticket") or {}
        # İstenen alanlar dönmeli
        for k in want:
            self.assertIn(k, tk)
        # Endpoint her zaman shadow_effective ekliyor; sadece varlığını doğrula
        self.assertIn("shadow_effective", tk)

    def test_get_tickets_by_team_and_user(self):
        team, user = _ensure_team_and_member()
        t = _new_ticket("Team List")
        # Team bazlı liste
        by_team = frappe.call(
            "helpdesk.api.ingest.get_tickets_by_team",
            team=team,
            status=None,
            limit=50,
            start=0,
        )
        names_by_team = {cstr(r.get("name")) for r in (by_team.get("tickets") or [])}
        self.assertIn(cstr(t), names_by_team)
        # User bazlı (ToDo üzerinden atama oluşturalım)
        todo = frappe.new_doc("ToDo")
        todo.reference_type = "HD Ticket"
        todo.reference_name = t
        todo.allocated_to = user
        todo.description = "Test assignment"
        todo.insert(ignore_permissions=True)
        frappe.db.commit()
        by_user = frappe.call(
            "helpdesk.api.ingest.get_tickets_by_user",
            user=user,
            status=None,
            limit=50,
            start=0,
        )
        names_by_user = {cstr(r.get("name")) for r in (by_user.get("tickets") or [])}
        self.assertIn(cstr(t), names_by_user)

    def test_get_articles_and_routing_context(self):
        # get_articles çalışmalı (boş sistemde de boş/ok döner)
        arts = frappe.call("helpdesk.api.ingest.get_articles", q="", limit=5)
        self.assertTrue(arts.get("ok"))
        self.assertIn("articles", arts)
        # routing context
        ctx = frappe.call("helpdesk.api.ingest.get_routing_context")
        self.assertTrue(ctx.get("ok"))
        self.assertIn("teams", ctx.get("context", {}))

    def test_get_shadow_status(self):
        t = _new_ticket("Shadow Status")
        # Başlangıç (global veya ticket gölge açık/kapalı olabilir) sadece anahtarlar var mı bak
        st0 = frappe.call("helpdesk.api.ingest.get_shadow_status", ticket=t)
        self.assertIn("effective", st0)
        # Ticket-level shadow ON
        frappe.call("helpdesk.api.ingest.set_flags", ticket=t, shadow_mode=1)
        st1 = frappe.call("helpdesk.api.ingest.get_shadow_status", ticket=t)
        self.assertTrue(st1.get("effective"), "Ticket-level shadow açılınca effective True olmalı")
        # Ticket-level shadow OFF
        frappe.call("helpdesk.api.ingest.set_flags", ticket=t, shadow_mode=0)
        st2 = frappe.call("helpdesk.api.ingest.get_shadow_status", ticket=t)
        # Global shadow açık olabilir; bu yüzden sadece ticket bayrağını da kontrol edelim
        self.assertIn("ticket_shadow", st2)


class TestSetterAndUpdateEndpoints(FrappeTestCase):
    def test_ingest_summary_append_and_clean(self):
        t = _new_ticket("HTML Clean")
        res1 = frappe.call(
            "helpdesk.api.ingest.ingest_summary",
            ticket=t,
            summary="<p>Hello <b>World</b></p>",
            append=0,
            clean_html=1,
        )
        self.assertTrue(res1.get("ok"))
        tk = frappe.call("helpdesk.api.ingest.get_ticket", ticket=t).get("ticket")
        self.assertNotIn("<p>", tk.get("ai_summary", ""))
        res2 = frappe.call(
            "helpdesk.api.ingest.ingest_summary",
            ticket=t,
            summary="Second line",
            append=1,
            clean_html=1,
        )
        self.assertTrue(res2.get("ok"))
        tk2 = frappe.call("helpdesk.api.ingest.get_ticket", ticket=t).get("ticket")
        self.assertIn("Second line", tk2.get("ai_summary", ""))
        self.assertIn("\n", tk2.get("ai_summary", ""))

    def test_set_reply_suggestion_and_sentiment_and_metrics(self):
        t = _new_ticket("Setters")
        # reply suggestion
        rs = frappe.call("helpdesk.api.ingest.set_reply_suggestion", ticket=t, text="Hi", append=0, clean_html=1)
        self.assertTrue(rs.get("ok"))
        # sentiment + invalid select yolu
        ok = frappe.call(
            "helpdesk.api.ingest.set_sentiment",
            ticket=t,
            last_sentiment="Neutral",
            sentiment_trend="Stable",
            effort_score=0.25,
            effort_band="Low",
        )
        self.assertTrue(ok.get("ok"))
        with self.assertRaises(frappe.ValidationError):
            frappe.call("helpdesk.api.ingest.set_sentiment", ticket=t, effort_band="Ultra")
        # metrics
        m = frappe.call("helpdesk.api.ingest.set_metrics", ticket=t, effort_score=0.55, cluster_hash="abc123")
        self.assertTrue(m.get("ok"))

    def test_update_ticket_whitelist_link_and_reject(self):
        t = _new_ticket("Update Ticket")
        team, _ = _ensure_team_and_member()
        # Geçerli link alanı
        up1 = frappe.call("helpdesk.api.ingest.update_ticket", ticket=t, fields={"agent_group": team})
        self.assertTrue(up1.get("ok"))
        # Geçersiz link alanı
        with self.assertRaises(frappe.ValidationError):
            frappe.call("helpdesk.api.ingest.update_ticket", ticket=t, fields={"agent_group": "NOPE_TEAM_X"})
        # Whitelist dışı alan reddi
        rej = frappe.call("helpdesk.api.ingest.update_ticket", ticket=t, fields={"raised_by": "hacker@example.com"})
        self.assertFalse(rej.get("ok"))
        self.assertIn("No allowed", cstr(rej.get("error")))

    def test_shadow_mode_preview_and_override(self):
        t = _new_ticket("Shadow Preview")
        # Ticket-level shadow ON (respect_shadow False olduğu için direkt yazılır)
        _ = frappe.call("helpdesk.api.ingest.set_flags", ticket=t, shadow_mode=1)
        # Shadow açıkken yazma -> preview dönmeli, DB değişmemeli
        prev = frappe.call(
            "helpdesk.api.ingest.ingest_summary",
            ticket=t,
            summary="SHD-TICKET-ONLY",
            append=0,
            clean_html=1,
        )
        self.assertIsInstance(prev, dict)
        self.assertTrue(prev.get("ok") and prev.get("shadow") and "preview" in prev)
        tk1 = frappe.call("helpdesk.api.ingest.get_ticket", ticket=t).get("ticket")
        self.assertNotEqual(tk1.get("ai_summary"), "SHD-TICKET-ONLY")
        # Override ile yazma
        over = frappe.call(
            "helpdesk.api.ingest.update_ticket",
            ticket=t,
            fields={"ai_summary": "OVERRIDDEN-DESPITE-SHADOW"},
            ignore_shadow=1,
        )
        self.assertTrue(over.get("ok"))
        tk2 = frappe.call("helpdesk.api.ingest.get_ticket", ticket=t).get("ticket")
        self.assertEqual(tk2.get("ai_summary"), "OVERRIDDEN-DESPITE-SHADOW")
        # Kapat
        _ = frappe.call("helpdesk.api.ingest.set_flags", ticket=t, shadow_mode=0)


class TestKBRequests(FrappeTestCase):
    def test_kb_requests_all_variants(self):
        # Link doğrulaması için gerçek bir HD Article oluştur
        art = frappe.new_doc("HD Article")
        # Bu DocType kurulumdan kurulu olmayabilir; alan adları değişkense minimal alanlarla bırak
        if hasattr(art, "title"):
            art.title = "Routing Rules"
        if hasattr(art, "subject") and not getattr(art, "title", None):
            art.subject = "Routing Rules"
        art.insert(ignore_permissions=True)
        frappe.db.commit()
        payload = {
            "subject": "RR policy missing edge cases",
            "priority": "High",
            "target_doctype": "HD Article",
            "target_name": art.name,  # mevcut isim
            "target_path": "/kb/ops/assignment-policy",
            "tags": "ops,assignment",
            "current_summary": "Old article lacks fallback",
            "proposed_changes": "Add fallback and SLA caveats",
            "references": "RFC-421",
            "attachment": "policy-v3.pdf",
            "breaking_change": 0,
        }
        n1 = frappe.call("helpdesk.api.ingest.request_kb_new_article", fields=payload)
        self.assertTrue(n1.get("ok") and n1.get("change_type") == "New Article")
        u1 = frappe.call("helpdesk.api.ingest.request_kb_update", fields={**payload, "subject": "RR policy update"})
        self.assertTrue(u1.get("ok") and u1.get("change_type") == "Update")
        f1 = frappe.call("helpdesk.api.ingest.request_kb_fix", fields={"subject": "Typo in RR policy"})
        self.assertTrue(f1.get("ok") and f1.get("change_type") == "Fix")
        d1 = frappe.call("helpdesk.api.ingest.report_kb_wrong_document", fields={"subject": "RR policy obsolete"})
        self.assertTrue(d1.get("ok") and d1.get("change_type") == "Deprecate")
        # subject eksikse ValidationError
        with self.assertRaises(frappe.ValidationError):
            frappe.call("helpdesk.api.ingest.request_kb_new_article", fields={"priority": "Low"})


class TestProblemTickets(FrappeTestCase):
    def test_problem_ticket_create_update_preview_and_list(self):
        # Create (strict=1 default)
        create = frappe.call(
            "helpdesk.api.ingest.upsert_problem_ticket",
            name=None,
            fields={
                "subject": f"Prob-{uuid.uuid4().hex[:6]}",
                "impact": "Users affected",
                "status": "Open",
                "severity": "High",
            },
            lookup_by=None,
            preview=0,
            normalize_html=1,
            strict=1,
        )
        self.assertTrue(create.get("ok"))
        prob_name = create.get("name")
        # Update no-change -> no_change True
        upd = frappe.call(
            "helpdesk.api.ingest.upsert_problem_ticket",
            name=prob_name,
            fields={"impact": "Users affected"},
            strict=1,
        )
        self.assertTrue(upd.get("ok"))
        # Preview mode
        prev = frappe.call(
            "helpdesk.api.ingest.upsert_problem_ticket",
            name=prob_name,
            fields={"impact": "Preview only"},
            preview=1,
        )
        self.assertTrue(prev.get("ok") and prev.get("preview"))
        # Invalid select
        with self.assertRaises(frappe.ValidationError):
            frappe.call(
                "helpdesk.api.ingest.upsert_problem_ticket",
                name=prob_name,
                fields={"status": "WontDo"},
            )
        # List & get
        lst = frappe.call("helpdesk.api.ingest.list_problem_tickets", status="Open", limit=10)
        self.assertTrue(lst.get("ok"))
        self.assertIn("problems", lst)
        got = frappe.call("helpdesk.api.ingest.get_problem_ticket", name=prob_name)
        self.assertTrue(got.get("ok"))
        self.assertEqual(got.get("problem", {}).get("name"), prob_name)
