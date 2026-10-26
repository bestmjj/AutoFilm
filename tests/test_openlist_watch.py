"""Regression tests for OpenList incremental monitor path and state safety."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.modules.alist2strm.alist2strm import Alist2Strm


class WatchPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.worker = Alist2Strm.__new__(Alist2Strm)
        self.worker.source_dir = "/媒体"
        self.worker.target_dir = self.root
        self.worker.flatten_mode = False
        self.worker._watch_state_path = self.root / "state.json"

    def test_nested_paths_and_case_insensitive_video(self):
        video = SimpleNamespace(name="E01.MKV", suffix=".MKV")
        resolved = self.worker._Alist2Strm__get_local_path(
            video, "/媒体/电视剧/第一季/E01.MKV"
        )
        self.assertEqual(resolved, self.root / "电视剧/第一季/E01.strm")

    def test_rejects_parent_traversal_and_outside_roots(self):
        video = SimpleNamespace(name="E01.mkv", suffix=".mkv")
        for remote in ("/媒体/../other/E01.mkv", "/其他/E01.mkv", "媒体/E01.mkv"):
            with self.subTest(remote=remote), self.assertRaises(ValueError):
                self.worker._Alist2Strm__get_local_path(video, remote)

    def test_does_not_escape_target_via_symlink(self):
        other = self.root / "elsewhere"
        other.mkdir()
        (self.root / "电视剧").symlink_to(other, target_is_directory=True)
        self.worker.target_dir = self.root / "output"
        self.worker.target_dir.mkdir()
        (self.worker.target_dir / "电视剧").symlink_to(other, target_is_directory=True)
        video = SimpleNamespace(name="E01.mp4", suffix=".mp4")
        with self.assertRaises(ValueError):
            self.worker._Alist2Strm__get_local_path(video, "/媒体/电视剧/E01.mp4")

    def test_absent_or_invalid_baseline(self):
        self.assertIsNone(self.worker._read_watch_state())
        self.worker._watch_state_path.write_text("not-json", encoding="utf-8")
        self.assertIsNone(self.worker._read_watch_state())


class WatchStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_checkpoint_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = Alist2Strm.__new__(Alist2Strm)
            worker._watch_state_path = Path(directory) / "watch-state" / "scan.json"
            snapshot = {"/媒体/电视剧/E01.mp4": {"size": 12, "modified": ""}}
            await worker._save_watch_state(snapshot)
            self.assertEqual(worker._read_watch_state(), snapshot)
            self.assertEqual(
                json.loads(worker._watch_state_path.read_text())["version"], 1
            )
            self.assertFalse(list(worker._watch_state_path.parent.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
