import tempfile
import unittest
from pathlib import Path

from paper_kestrel.recovery import CheckpointJournal, RecoveryBlocked
from paper_kestrel.state import RunStore


class SharedAuthority:
    def __init__(self):
        self.data = {}

    def claim(self, key, fingerprint, candidate):
        saved = self.data.get(key)
        if saved is None:
            self.data[key] = [fingerprint, "STARTED", None, None]
            return {"accepted": True, "cached": False}
        if saved[0] != fingerprint or saved[1] != "COMPLETED":
            raise RecoveryBlocked("Uncertain or changed remote step")
        if saved[3] is not None and saved[3] != candidate:
            raise RecoveryBlocked("Candidate not restored")
        return {"accepted": True, "cached": True, "result": saved[2]}

    def complete(self, key, fingerprint, candidate, result):
        saved = self.data[key]
        if saved[0] != fingerprint or saved[1] != "STARTED":
            raise RecoveryBlocked("Conflicting completion")
        self.data[key] = [fingerprint, "COMPLETED", result, candidate]


class CrossRunnerTests(unittest.TestCase):
    def test_commit_survives_new_runner(self):
        with tempfile.TemporaryDirectory() as folder:
            authority = SharedAuthority()
            first = RunStore(Path(folder) / "first.sqlite", "run-1")
            second = RunStore(Path(folder) / "second.sqlite", "run-1")
            for store in (first, second):
                store.initialize(spec="spec", master="master", cap=.75, milestone="TSAND")
            try:
                a = CheckpointJournal(first, remote=authority)
                b = CheckpointJournal(second, remote=authority)
                self.assertIsNone(a.begin("plan", {"step": 1}))
                with self.assertRaises(RecoveryBlocked):
                    b.begin("plan", {"step": 1})
                a.complete("plan", {"step": 1}, {"result": "ok"})
                self.assertEqual(b.begin("plan", {"step": 1}), {"result": "ok"})
            finally:
                first.db.close()
                second.db.close()

    def test_write_replay_requires_candidate_match(self):
        with tempfile.TemporaryDirectory() as folder:
            authority = SharedAuthority()
            a = RunStore(Path(folder) / "a.sqlite", "run-1")
            b = RunStore(Path(folder) / "b.sqlite", "run-1")
            for store in (a, b):
                store.initialize(spec="spec", master="master", cap=.75, milestone="TSAND")
            try:
                ja = CheckpointJournal(a, remote=authority)
                jb = CheckpointJournal(b, remote=authority)
                ja.begin("write", {"work": 1}, candidate_sha="a"*64)
                ja.complete("write", {"work": 1}, {"summary": "ok"}, candidate_sha="b"*64)
                with self.assertRaises(RecoveryBlocked):
                    jb.begin("write", {"work": 1}, candidate_sha="c"*64)
                self.assertEqual(jb.begin("write", {"work": 1}, candidate_sha="b"*64),
                                 {"summary": "ok"})
            finally:
                a.db.close()
                b.db.close()
