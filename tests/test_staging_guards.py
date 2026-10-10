"""Non-negotiable V2 safety boundary in the public test branch.

These assertions intentionally prevent accidental enabling of paid crew,
production-targeted PRs and privileged staging smoke jobs during migration.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SafeStagingWorkflowTests(unittest.TestCase):
    def test_paid_workflow_is_unconditionally_blocked_before_clone(self):
        workflow = (ROOT / ".github/workflows/crew.yml").read_text(encoding="utf-8")
        gate = workflow.index("Migration safety gate (non-bypassable)")
        clone = workflow.index("Clone split workspaces")
        self.assertLess(gate, clone)
        self.assertIn("exit 78", workflow[gate:clone])

    def test_agent_prs_never_target_main(self):
        workflow = (ROOT / ".github/workflows/crew.yml").read_text(encoding="utf-8")
        self.assertIn('TARGET_BASE_BRANCH: "t-sand"',workflow)
        self.assertIn('test "$TARGET_BASE_BRANCH" = "t-sand"', workflow)
        self.assertIn('--base "$TARGET_BASE_BRANCH"',workflow)
        self.assertNotIn("--base main", workflow)

    def test_clone_only_public_staging_branches(self):
        workflow = (ROOT / ".github/workflows/crew.yml").read_text(encoding="utf-8")
        self.assertIn('MatteoCurro/winter-opal',workflow)
        self.assertIn('MatteoCurro/quiet-spindle',workflow)
        self.assertIn('ref: ${{ github.sha }}',workflow)
        self.assertIn('--branch "$TARGET_BASE_BRANCH" --single-branch',workflow)

    def test_remote_gateway_hard_denies_paid_llm(self):
        gateway = (ROOT / "edge/crew-budget/index.ts").read_text(encoding="utf-8")
        self.assertIn('const PAID_ADMISSION_ENABLED = false',gateway)
        self.assertIn("if (!canary && !jarvisV2 && (!PAID_ADMISSION_ENABLED",gateway)
        self.assertIn('const APPROVED_JARVIS_V2_MILESTONE = "JARVIS_V2_REVIEW_20261010"',gateway)
        self.assertIn("jarvisV2 && !JARVIS_V2_ADMISSION_ENABLED",gateway)
        self.assertIn('CANARY_WORKFLOW = "Jarvis TSAND review canary"', gateway)
        self.assertIn('p_milestone: body.milestone', gateway)
        self.assertIn('crew_budget_reserve_jarvis_canary', gateway)

    def test_staging_preview_has_no_push_permissions_or_deployment(self):
        workflow = (ROOT / ".github/workflows/crewai-offline-audit.yml").read_text(encoding="utf-8")
        staging = workflow.split("  staging_preview:",1)[1].split("  oidc_tsand:",1)[0]
        self.assertIn("contents: read",staging)
        self.assertNotIn("contents: write",staging)
        self.assertNotIn("gh pr create",staging)
        self.assertNotIn("git push",staging)
        self.assertIn("GH_TOKEN: ''",staging)

if __name__=="__main__":
    unittest.main()
