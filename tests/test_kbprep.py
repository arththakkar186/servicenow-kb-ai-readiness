from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kbprep.__main__ import run  # noqa: E402
from kbprep.export import SnClient, load_raw  # noqa: E402
from kbprep.mock_instance import NAMES, MockServiceNow, build_dataset  # noqa: E402
from kbprep.rank import rank_articles, request_mix  # noqa: E402
from kbprep.reconcile import reconcile_table  # noqa: E402
from kbprep.redact import PUBLISHED_FIELDS, Redactor, html_to_text, minimise  # noqa: E402
from kbprep.versions import current_articles  # noqa: E402

TODAY = datetime(2026, 11, 1)
DOMAINS = ("corp.example", "service-now.com")


class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cls.mock = MockServiceNow()
        cls.fig = run(cls.out, SnClient("mock", token="", opener=cls.mock, page_size=500), TODAY, DOMAINS, tuple(NAMES))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_read_only(self):
        self.assertTrue(all(r.get_method() == "GET" for r in self.mock.requests))

    def test_raw_checksums_verified(self):
        load_raw(self.out)  # does not raise
        p = self.out / "raw" / "task.json"
        original = p.read_bytes()
        try:
            p.write_bytes(original.replace(b"INC", b"INX", 1))
            with self.assertRaises(ValueError):
                load_raw(self.out)
        finally:
            p.write_bytes(original)

    def test_acl_gap_is_explained(self):
        kb = next(r for r in self.fig["reconciliation"] if r["table"] == "kb_knowledge")
        restricted = sum(1 for r in self.mock.data["kb_knowledge"] if r["_restricted"])
        self.assertEqual(kb["gap"], restricted)
        self.assertIn("row-level ACLs", kb["conclusion"])
        task = next(r for r in self.fig["reconciliation"] if r["table"] == "task")
        self.assertEqual(task["gap"], 0)

    def test_one_file_per_current_article_with_five_fields(self):
        files = list((self.out / "library").glob("*.md"))
        self.assertEqual(len(files), self.fig["versions"]["current_articles"])
        front = files[0].read_text().split("---")[1]
        keys = {l.split(":")[0] for l in front.strip().splitlines()}
        self.assertEqual(keys | {"body"}, set(PUBLISHED_FIELDS))

    def test_library_contains_no_pii(self):
        text = "\n".join(p.read_text() for p in (self.out / "library").glob("*.md"))
        self.assertNotRegex(text, r"@corp\.example|intranet\.corp\.example|416-555-\d{4}|\b10\.\d+\.\d+\.\d+\b")
        for n in NAMES:
            self.assertNotIn(n, text)
        self.assertIn("support.microsoft.com", text, "public vendor links must be kept")

    def test_redaction_report_totals_match_log(self):
        rows = (self.out / "redaction_report.csv").read_text().splitlines()[1:]
        total = sum(int(r.split(",")[-8]) for r in rows) if rows else 0
        self.assertEqual(total, self.fig["redactions"]["total"])

    def test_figures_rebuild_from_raw(self):
        raw = load_raw(self.out)
        kept, dropped = current_articles(raw["kb_knowledge"], TODAY.date())
        self.assertEqual(len(kept), self.fig["versions"]["current_articles"])
        self.assertEqual(len(kept) + len(dropped), self.fig["raw_manifest"]["kb_knowledge"]["rows"])


class Units(unittest.TestCase):
    def test_version_rules(self):
        base = {"number": "KB1", "latest": "true", "workflow_state": "published", "valid_to": "2100-01-01"}
        rows = [dict(base, version="1.0", latest="false"), dict(base, version="2.0"),
                dict(base, number="KB2", workflow_state="retired"), dict(base, number="KB3", valid_to="2026-01-01"),
                dict(base, number="KB4", workflow_state="draft")]
        kept, dropped = current_articles(rows, date(2026, 11, 1))
        self.assertEqual([(k["number"], k["version"]) for k in kept], [("KB1", "2.0")])
        self.assertEqual(sorted(d["_drop_reason"].split(" (")[0] for d in dropped),
                         ["expired", "not published", "retired", "superseded by a newer version"])

    def test_two_current_versions_is_an_error(self):
        r = {"number": "KB1", "latest": "true", "workflow_state": "published", "valid_to": ""}
        with self.assertRaises(ValueError):
            current_articles([dict(r), dict(r)], date(2026, 11, 1))

    def test_reconcile_detects_duplicates_and_deletions(self):
        rows = [{"sys_id": "a"}, {"sys_id": "a"}, {"sys_id": "b"}]
        res = reconcile_table("t", rows, aggregate_count=3, recount=2)
        self.assertIn("1 duplicate", res["checks"][0]["result"])
        self.assertIn("count changed", res["checks"][2]["result"])
        self.assertIn("unexplained", res["conclusion"])

    def test_redactor(self):
        r = Redactor(DOMAINS, ("Avery Abbott",))
        html = ('<p>Contact Avery Abbott (avery.abbott@corp.example) or Sam Rivers, call (416) 555-0101, '
                'host 192.168.10.5, <a href="https://wiki.corp.example/x">wiki</a>, '
                '<a href="https://learn.microsoft.com/">docs</a>, ask Sam Rivers.</p>')
        out = r.scrub("KB1", html_to_text(html))
        for leak in ("Avery Abbott", "avery.abbott", "555-0101", "192.168.10.5", "wiki.corp.example", "ask Sam Rivers"):
            self.assertNotIn(leak, out)
        self.assertIn("learn.microsoft.com", out)
        self.assertEqual({e["type"] for e in r.log}, {"name", "email", "phone", "ip_address", "internal_link"})
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{16}", e["value_sha256"]) for e in r.log), "log stores hashes, not values")

    def test_minimise_drops_unlisted_fields(self):
        a = {"number": "KB1", "short_description": "T", "kb_category": "C", "text": "<p>x</p>",
             "sys_updated_on": "2026-01-01 10:00:00", "author": "Avery Abbott", "sys_id": "123"}
        self.assertEqual(set(minimise(a, Redactor(DOMAINS))), set(PUBLISHED_FIELDS))

    def test_rank_ignores_links_to_non_current_versions(self):
        current = [{"number": "KB1", "short_description": "t", "kb_category": "c"}]
        links = [{"kb_number": "KB1", "sys_created_on": "2026-10-01 00:00:00"},
                 {"kb_number": "KB9", "sys_created_on": "2026-10-01 00:00:00"}]
        r = rank_articles(current, links, TODAY)
        self.assertEqual((r[0]["linked_tickets"], r[0]["linked_last_12m"]), (1, 1))

    def test_request_mix_top_item(self):
        data = build_dataset()
        mix = request_mix(data["task"], TODAY)
        self.assertEqual(mix["top_item"], "Local admin rights (temporary)")
        self.assertGreater(mix["top_item_share_pct"], 50)


if __name__ == "__main__":
    unittest.main()
