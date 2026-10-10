"""End-to-end contract rehearsal; zero provider tokens and no repository writes."""
import unittest
from paper_kestrel.simulation import rehearse

class SimulationTests(unittest.TestCase):
    def test_ux_feedback_changes_implementation_once(self):
        result = rehearse("ux_revision")
        self.assertTrue(result.accepted)
        self.assertEqual(result.steps.count("ux:review"),1)
        self.assertEqual(result.steps.count("engineer:revision"),1)
        self.assertIn("reviewer:independent",result.steps)
        self.assertGreaterEqual(result.delivered_events,2)
        self.assertEqual(result.pending_events,0)

    def test_ux_approval_no_unnecessary_revision(self):
        result = rehearse("approved")
        self.assertTrue(result.accepted)
        self.assertNotIn("engineer:revision",result.steps)

    def test_crash_does_not_reinvoke_engineer(self):
        result = rehearse("crash")
        self.assertFalse(result.accepted)
        self.assertTrue(result.blocked_on_crash)
        self.assertNotIn("engineer:revision",result.steps)

    def test_independent_qa_can_block(self):
        result = rehearse("review_block")
        self.assertFalse(result.accepted)
        self.assertEqual(result.pending_events,0)

if __name__=="__main__":
    unittest.main()
