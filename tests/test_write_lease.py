"""Offline regression: writes cannot bypass a current SQLite lease."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_kestrel.state import RunStore
from paper_kestrel.tools import WriteFileTool, ReplaceInFileTool


class WriteLeaseTests(unittest.TestCase):
    def test_fail_closed_and_authorized_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "work"
            root.mkdir()
            state_path = Path(temp) / "ledger.sqlite3"
            store = RunStore(state_path, "run-x")
            store.initialize(spec="a", master="b", cap=.75, milestone="test")
            env = {
                "AGENT_WORKSPACE": str(root),
                "RUN_STATE_DB": str(state_path),
                "RUN_STATE_ID": "run-x",
                "ACTIVE_WORK_ITEM": "task-a",
            }
            with patch.dict(os.environ, env, clear=False):
                with self.assertRaises(PermissionError):
                    WriteFileTool()._run(path="new.txt", content="hello")
                store.acquire_writer(str(root.resolve()), "task-a")
                self.assertIn("WROTE", WriteFileTool()._run(path="new.txt", content="hello"))
                self.assertIn("REPLACED", ReplaceInFileTool()._run(
                    path="new.txt", old="hello", new="world"))
                self.assertEqual((root/"new.txt").read_text(), "world")
                with patch.dict(os.environ, {"ACTIVE_WORK_ITEM":"task-b"}):
                    with self.assertRaises(PermissionError):
                        ReplaceInFileTool()._run(path="new.txt",old="world",new="bad")
                store.release_writer(str(root.resolve()), "task-a")
                with self.assertRaises(PermissionError):
                    WriteFileTool()._run(path="new.txt", content="bad")
            store.db.close()


if __name__ == "__main__":
    unittest.main()
