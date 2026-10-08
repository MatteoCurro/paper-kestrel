"""Run-level idempotency with CrewAI mocked: no provider, no product repository."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from paper_kestrel.recovery import RecoveryBlocked
from paper_kestrel.state import RunStore
from paper_kestrel.main import run_single


class RunRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RunStore(Path(self.tmp.name)/"state.sqlite3","404:1")
        self.store.initialize(spec="spec",master="master",cap=.75,milestone="TSAND")
        self.agent = SimpleNamespace(role="Test Reviewer",
                                     llm=SimpleNamespace(model="fake-model"))
        self.emitter = SimpleNamespace(run_store=self.store,emit=lambda *a,**k: None)

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def test_completed_llm_kickoff_replays_cached_result(self):
        with patch("paper_kestrel.main.EMITTER",self.emitter):
            with patch("paper_kestrel.main.Task"), patch("paper_kestrel.main.Crew") as crew:
                crew.return_value.kickoff.return_value="review done"
                self.assertEqual(run_single(self.agent,"input","expected"),"review done")
                self.assertEqual(run_single(self.agent,"input","expected"),"review done")
                crew.return_value.kickoff.assert_called_once()

    def test_interrupted_llm_is_not_automatically_retried(self):
        with patch("paper_kestrel.main.EMITTER",self.emitter):
            with patch("paper_kestrel.main.Task"), patch("paper_kestrel.main.Crew") as crew:
                crew.return_value.kickoff.side_effect=RuntimeError("uncertain charge")
                with self.assertRaises(RuntimeError):
                    run_single(self.agent,"input","expected")
                with self.assertRaises(RecoveryBlocked):
                    run_single(self.agent,"input","expected")
                crew.return_value.kickoff.assert_called_once()

    def test_changed_prompt_cannot_replay_old_response(self):
        with patch("paper_kestrel.main.EMITTER",self.emitter):
            with patch("paper_kestrel.main.Task"), patch("paper_kestrel.main.Crew") as crew:
                crew.return_value.kickoff.return_value="ok"
                self.assertEqual(run_single(self.agent,"first input","expected"),"ok")
                self.assertEqual(run_single(self.agent,"second input","expected"),"ok")
                self.assertEqual(crew.return_value.kickoff.call_count,2)


if __name__=="__main__":
    unittest.main()
