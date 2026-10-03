"""Evidence tags on memory writes (Kai, 2026-10-03)."""

import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))
sys.path.insert(0, str(TESTS_DIR.parent))

import _test_environment  # noqa: F401

import schema
from evidence_tags import (EvidenceTagError, apply_header, build_header, parse_header,
                           strip_header, tag_keywords)


class EvidenceHeaderTests(unittest.TestCase):
    def test_builds_full_header(self):
        header = build_header("verified", "gcloud run services describe", "2026-10-03T21:40+07:00", "claude-opus-5-5")
        self.assertEqual(header, "[verified | 2026-10-03T21:40+07:00 | by claude-opus-5-5 | evidence: gcloud run services describe]")
        self.assertEqual(parse_header(header)["tag"], "verified")

    def test_rejects_missing_or_unknown_tag(self):
        for tag in ("", "true", "checking", "reported"):
            with self.assertRaises(EvidenceTagError):
                build_header(tag)

    def test_executed_and_verified_need_evidence(self):
        for tag in ("executed", "verified"):
            with self.assertRaises(EvidenceTagError):
                build_header(tag, evidence="  ")
        self.assertTrue(build_header("speculated").startswith("[speculated | "))

    def test_rejects_bad_as_of(self):
        for bad in ("yesterday", "2026-10-03 21:40", "2026-10-03T21:40"):
            with self.assertRaises(EvidenceTagError):
                build_header("assumed", as_of=bad)
        self.assertIn("| 2026-10-03 |", build_header("decided", as_of="2026-10-03"))

    def test_default_as_of_is_utc_plus_7(self):
        self.assertRegex(build_header("planned"), r"^\[planned \| \d{4}-\d{2}-\d{2}T\d{2}:\d{2}\+07:00 \| by unspecified\]$")

    def test_restore_replaces_old_header(self):
        first = apply_header("GR prod rev is 00156", "speculated", by="luna")
        second = apply_header(first, "verified", "gcloud describe", "2026-10-03T21:40+07:00", "claude")
        self.assertEqual(second.count("\n"), 1)
        self.assertEqual(strip_header(second), "GR prod rev is 00156")
        self.assertEqual(parse_header(second)["tag"], "verified")

    def test_free_text_cannot_break_header(self):
        header = build_header("verified", "rows] dropped\nnext", "2026-10-03", "a|b")
        self.assertIsNotNone(parse_header(header))
        self.assertNotIn("\n", header)

    def test_tag_keyword_added_once(self):
        self.assertEqual(tag_keywords("gr prod tag:verified", "verified"), "gr prod tag:verified")
        self.assertEqual(tag_keywords("", "decided"), "tag:decided")


class EvidenceMcpTests(unittest.TestCase):
    def test_store_memory_rejects_untagged_and_stores_header(self):
        from agy_memory_mcp import store_memory
        with self.assertRaises(EvidenceTagError):
            store_memory("ev.fact", "GR prod serves AUG-P", tag="")
        with self.assertRaises(EvidenceTagError):
            store_memory("ev.fact", "GR prod serves AUG-P", tag="verified")
        store_memory("ev.fact", "GR prod serves AUG-P", tag="verified", category="work",
                     evidence="rev 00156-gwg", as_of="2026-10-03T21:40+07:00", by="claude-opus-5-5")
        with schema.db_session() as conn:
            fact, keywords = conn.execute("SELECT fact, keywords FROM memories WHERE id='ev.fact'").fetchone()
        self.assertEqual(fact, "[verified | 2026-10-03T21:40+07:00 | by claude-opus-5-5 | evidence: rev 00156-gwg]\nGR prod serves AUG-P")
        self.assertIn("tag:verified", keywords)

    def test_learning_and_episode_require_tag(self):
        from agy_memory_mcp import record_episode, record_learning
        with self.assertRaises(EvidenceTagError):
            record_learning("ev.lrn", "workflow", "Check ingestion first", tag="maybe")
        with self.assertRaises(EvidenceTagError):
            record_episode("ev.ep", "work", "Title", "Narrative", tag="")
        record_learning("ev.lrn", "workflow", "Check ingestion first", tag="inferred", by="claude")
        with schema.db_session() as conn:
            insight = conn.execute("SELECT insight FROM learnings WHERE id='ev.lrn'").fetchone()[0]
        self.assertEqual(parse_header(insight)["tag"], "inferred")

    def test_search_returns_reading_rule(self):
        import json
        from agy_memory_mcp import search_memory
        self.assertIn("reading_rule", json.loads(search_memory("anything at all", limit=1)))


class ConsolidationTagTests(unittest.TestCase):
    def test_merge_keeps_shared_tag_with_oldest_as_of(self):
        from agy_memory import _merge_tag
        rows = [("a", "infra", apply_header("x", "verified", "q1", "2026-10-01", "c")),
                ("b", "infra", apply_header("y", "verified", "q2", "2026-10-03", "c"))]
        rows = [(r[0], r[1], r[2], "") for r in rows]
        text, kw = _merge_tag("merged x and y", "", rows)
        header = parse_header(text)
        self.assertEqual((header["tag"], header["as_of"]), ("verified", "2026-10-01"))
        self.assertIn("tag:verified", kw)

    def test_merge_of_mixed_tags_is_inferred(self):
        from agy_memory import _merge_tag
        rows = [("a", "infra", apply_header("x", "decided", by="c"), ""), ("b", "infra", "untagged y", "")]
        text, _ = _merge_tag("merged", "", rows)
        self.assertEqual(parse_header(text)["tag"], "inferred")

    def test_merge_of_untagged_sources_stays_untagged(self):
        from agy_memory import _merge_tag
        text, kw = _merge_tag("merged", "k", [("a", "infra", "x", ""), ("b", "infra", "y", "")])
        self.assertEqual((text, kw), ("merged", "k"))


if __name__ == "__main__":
    unittest.main()
