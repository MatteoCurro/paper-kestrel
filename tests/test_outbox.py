"""Jarvis outbox tests use no network, OIDC or model API."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from paper_kestrel.state import RunStore
from paper_kestrel.jarvis import JarvisEmitter


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RunStore(Path(self.tmp.name) / "run.sqlite3", "123:1")
        self.store.initialize(spec="spec", master="plan", cap=.75, milestone="test")
        with patch.dict("os.environ", {}, clear=True):
            self.emitter = JarvisEmitter()
        self.emitter.run_store = self.store
        self.emitter.run_id = "123"
        self.emitter.attempt = "1"
        self.emitter.spec_path = "orders/test.md"

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def test_event_enqueued_without_telemetry_and_not_lost(self):
        self.emitter.enabled = False
        self.emitter.emit("agent.started", "starting", event_key="agent:1")
        rows = self.store.pending_outbox()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1]["message"], "starting")
        self.assertEqual(rows[0][1]["event_key"], "agent:1")

    def test_deduplicated_event_key(self):
        self.emitter.enabled = False
        self.emitter.emit("agent.started", "starting", event_key="same")
        self.emitter.emit("agent.started", "repeated", event_key="same")
        self.assertEqual(len(self.store.pending_outbox()), 1)

    def test_retry_after_failed_ack_does_not_lose_event(self):
        self.emitter.enabled = False
        self.emitter.emit("agent.started", "starting", event_key="a")
        self.emitter.enabled = True
        self.emitter._post = Mock(side_effect=[False, True])
        self.assertEqual(self.emitter.flush_outbox(), 0)
        self.assertEqual(len(self.store.pending_outbox()), 1)
        self.assertEqual(self.emitter.flush_outbox(), 1)
        self.assertEqual(len(self.store.pending_outbox()), 0)
        self.assertEqual(self.emitter._post.call_count, 2)

    def test_transition_is_projected_as_jarvis_event(self):
        self.store.transition("010:plan","PLANNED",{"items":1})
        self.emitter.enabled = True
        emitted = []
        self.emitter._post = lambda payload: emitted.append(payload) or True
        self.assertEqual(self.emitter.flush_outbox(), 1)
        self.assertEqual(emitted[0]["event_type"], "run.state")
        self.assertEqual(emitted[0]["metadata"]["state"], "PLANNED")
        self.assertEqual(emitted[0]["github_run_id"], 123)

    def test_no_store_means_no_direct_http(self):
        self.emitter.run_store = None
        self.emitter.enabled = True
        self.emitter._post = Mock(side_effect=AssertionError("direct delivery forbidden"))
        with self.assertRaises(RuntimeError):
            self.emitter.emit("run.failed", "bad", event_key="failure")
        self.emitter._post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
