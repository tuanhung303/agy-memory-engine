import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _test_environment  # noqa: F401

import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agy_memory


class TestPruneSnapshots(unittest.TestCase):
    def setUp(self):
        self.archive = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.archive, ignore_errors=True)

    def _make(self, tag, n):
        files = []
        for i in range(n):
            f = self.archive / f"memory_db_backup_2026-10-11_{i:06d}_{tag}.bak"
            f.write_text("x")
            os.utime(f, (time.time() - (n - i), time.time() - (n - i)))
            files.append(f)
        return files

    def test_keeps_newest_and_other_tags(self):
        cons = self._make("consolidate", 23)
        opt = self._make("optimization", 3)
        manual = self.archive / "memory_db_backup_2026-10-11_000000_manual.bak"
        manual.write_text("x")
        with patch.object(agy_memory, "archive_path", return_value=self.archive):
            deleted = agy_memory.prune_snapshots("consolidate", keep=20, db_path="/tmp/x.db")
        self.assertEqual(deleted, 3)
        self.assertTrue(all(not f.exists() for f in cons[:3]))
        self.assertTrue(all(f.exists() for f in cons[3:]))
        self.assertTrue(all(f.exists() for f in opt))
        self.assertTrue(manual.exists())

    def test_rejects_glob_tag(self):
        with self.assertRaises(ValueError):
            agy_memory.prune_snapshots("*", keep=0)


if __name__ == "__main__":
    unittest.main()
