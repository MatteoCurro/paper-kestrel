"""Pure UX-feedback contract and independent feedback loop."""
import unittest
from paper_kestrel.ux_loop import UXCritique, critique_and_revise, requires_ux_review


class UXLoopTests(unittest.TestCase):
    def test_ui_files_trigger_critic(self):
        self.assertTrue(requires_ux_review(["public/app/index.html"]))
        self.assertTrue(requires_ux_review(["src/ui/Account.js"]))
        self.assertFalse(requires_ux_review(["server/ingestion.py"]))

    def test_approved_design_does_not_make_extra_calls(self):
        revisions = []
        answer = critique_and_revise(
            lambda: UXCritique(disposition="approve",summary="Accessible",
                               findings=["Optional nicer typography"]),
            lambda *args: revisions.append(args) or "changed",
        )
        self.assertFalse(answer.revised)
        self.assertEqual(revisions, [])

    def test_one_critic_engineer_handoff(self):
        calls = []
        def engineer(findings, acceptance):
            calls.append((findings, acceptance))
            return "Adjusted mobile focus and added assertion"
        answer = critique_and_revise(
            lambda: UXCritique(disposition="revise",summary="Form is hard to use",
                               findings=["Keyboard covers submit"],
                               acceptance_tests=["Submit remains visible when keyboard opens"]),
            engineer,
        )
        self.assertEqual(len(calls), 1)
        self.assertTrue(answer.revised)
        self.assertEqual(calls[0][0],("Keyboard covers submit",))

    def test_critic_cannot_request_vague_loop(self):
        with self.assertRaises(ValueError):
            critique_and_revise(
                lambda: UXCritique(disposition="revise",summary="Change it",findings=[]),
                lambda *_: "changed",
            )

    def test_engineer_must_return_handoff(self):
        with self.assertRaises(RuntimeError):
            critique_and_revise(
                lambda: UXCritique(disposition="revise",summary="Fix",findings=["Broken CTA"]),
                lambda *_: "",
            )


if __name__=="__main__":
    unittest.main()
