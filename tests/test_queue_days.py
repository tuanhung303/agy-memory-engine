import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _test_environment  # noqa: F401

import os
import shutil
import sqlite3
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from queue_manager import claim_batch, enqueue_turn, init_queue_db, pending_days


class TestClaimByDay(unittest.TestCase):
    """Daily reconcile claims one local calendar day at a time."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.queue_db = os.path.join(self.temp_dir, "queue.db")
        init_queue_db(self.queue_db)
        # Noon UTC lands on the same calendar day in every timezone from -11 to +11.
        for i, (chat, ts) in enumerate([
            ("chat-a", "2026-10-05 12:00:00"),
            ("chat-a", "2026-10-06 12:00:00"),
            ("chat-b", "2026-10-06 12:00:01"),
        ]):
            enqueue_turn(f"q{i}", f"a{i}", source="claude", chat_id=chat, db_path=self.queue_db)
            with sqlite3.connect(self.queue_db) as conn:
                conn.execute("UPDATE turn_queue SET created_at=? WHERE user_prompt=?", (ts, f"q{i}"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_pending_days_oldest_first(self):
        self.assertEqual(
            pending_days(db_path=self.queue_db),
            [{"day": "2026-10-05", "pending": 1}, {"day": "2026-10-06", "pending": 2}],
        )

    def test_claim_day_splits_one_chat_by_day(self):
        claim = claim_batch(batch_size=10, prefer_fresh=True, db_path=self.queue_db, day="2026-10-06")
        self.assertIsNotNone(claim)
        self.assertEqual([t["user_prompt"] for t in claim.turns], ["q1"])
        second = claim_batch(batch_size=10, prefer_fresh=True, db_path=self.queue_db, day="2026-10-06")
        self.assertEqual([t["user_prompt"] for t in second.turns], ["q2"])
        self.assertIsNone(claim_batch(batch_size=10, prefer_fresh=True, db_path=self.queue_db, day="2026-10-06"))
        self.assertEqual(pending_days(db_path=self.queue_db)[0]["day"], "2026-10-05")

    def test_expired_retry_respects_day(self):
        claim = claim_batch(batch_size=10, lease_duration_seconds=0, prefer_fresh=True,
                            db_path=self.queue_db, day="2026-10-05")
        self.assertEqual([t["user_prompt"] for t in claim.turns], ["q0"])
        other_day = claim_batch(batch_size=10, retry_delay_seconds=0, db_path=self.queue_db, day="2026-10-06")
        self.assertNotIn("q0", [t["user_prompt"] for t in other_day.turns])
        retry = claim_batch(batch_size=10, retry_delay_seconds=0, db_path=self.queue_db, day="2026-10-05")
        self.assertEqual([t["user_prompt"] for t in retry.turns], ["q0"])

    def test_no_day_keeps_old_behavior(self):
        claim = claim_batch(batch_size=10, prefer_fresh=True, db_path=self.queue_db)
        self.assertEqual([t["user_prompt"] for t in claim.turns], ["q0", "q1"])


if __name__ == "__main__":
    unittest.main()
