"""Strict read-only remote staging handoff rehearsal.

The CI runner clones ONLY the two public t-sand branches. This module modifies
clones and its ephemeral assembled workspace, never pushes, merges or deploys.
A generated PR manifest is just evidence, not an actual GitHub PR.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from .candidate_snapshot import capture, export_json, restore
from .split import assemble, sync_back


def git(work: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(work), *args],
        capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def verify_target(path: Path, expected: str) -> str:
    if git(path, "branch", "--show-current") != "t-sand":
        raise RuntimeError("Not checked out on t-sand; no preview allowed")
    actual = git(path, "remote", "get-url", "origin")
    normalized = actual.removesuffix(".git").rstrip("/")
    if normalized != f"https://github.com/{expected}":
        raise RuntimeError(f"Unexpected repository remote for staging: {expected}")
    if git(path, "status", "--porcelain"):
        raise RuntimeError("Source clone is dirty; no preview allowed")
    return git(path, "rev-parse", "HEAD")


def preview(repo_a: Path, repo_b: Path, output: Path) -> dict:
    original_a = verify_target(repo_a, "MatteoCurro/winter-opal")
    original_b = verify_target(repo_b, "MatteoCurro/quiet-spindle")
    with tempfile.TemporaryDirectory(prefix="crew-staging-preview-") as directory:
        root = Path(directory)
        assembled = root / "assembled"
        assemble(repo_a, repo_b, assembled)
        git(assembled, "init", "-q")
        git(assembled, "config", "user.name", "Crew TSAND preview")
        git(assembled, "config", "user.email", "ci@example.invalid")
        git(assembled, "add", "-A")
        git(assembled, "commit", "-qm", "ephemeral baseline")

        # Exactly one deliberate synthetic change, never app functional code.
        marker = assembled / "assets" / ".crew-tsand-handoff-smoke"
        marker.parent.mkdir(parents=True, exist_ok=True)
        if marker.exists():
            raise RuntimeError("Unexpected existing smoke marker")
        marker.write_text("TSAND dry-run; not a user-facing change\n", encoding="utf-8")
        snapshot = capture(assembled)

        # Replay into a separate local checkout of the baseline to prove the
        # captured patch can survive an ephemeral runner.
        replay = root / "replay"
        subprocess.run(
            ["git", "clone", "-q", "--no-hardlinks", str(assembled), str(replay)],
            check=True, capture_output=True,
        )
        restored = restore(replay, snapshot)
        if restored != snapshot["candidate_tree"]:
            raise RuntimeError("Snapshot candidate hash mismatch")

        # Existing split ownership rules map the marker to repo A.
        sync_back(assembled, repo_a, repo_b)
        changes_a = git(repo_a, "status", "--porcelain", "--untracked-files=all")
        changes_b = git(repo_b, "status", "--porcelain", "--untracked-files=all")
        if changes_a.strip() != "?? assets/.crew-tsand-handoff-smoke" or changes_b:
            raise RuntimeError(
                "Split created unrelated candidate changes; refuse PR preparation: "
                + repr((changes_a, changes_b))
            )
        if git(repo_a, "branch", "--show-current") != "t-sand":
            raise RuntimeError("Source branch unexpectedly changed")
        if git(repo_a, "rev-parse", "HEAD") != original_a:
            raise RuntimeError("Source commit unexpectedly changed")
        if git(repo_b, "rev-parse", "HEAD") != original_b:
            raise RuntimeError("Backend source commit unexpectedly changed")
        report = {
            "mode": "READ_ONLY_STAGING_PREVIEW",
            "staging_base": "t-sand",
            "repository_a": "MatteoCurro/winter-opal",
            "repository_b": "MatteoCurro/quiet-spindle",
            "source_commits": [original_a, original_b],
            "candidate_tree": restored,
            "candidate_files": ["assets/.crew-tsand-handoff-smoke"],
            "pr_preview": {
                "base": "t-sand",
                "head": "agent/dryrun-DO-NOT-PUSH",
                "draft": True,
                "created": False,
            },
            "production_deploy": False,
            "model_calls": 0,
        }
        output.mkdir(parents=True, exist_ok=True)
        (output/"staging-pr-preview.json").write_text(
            json.dumps(report,indent=2,sort_keys=True),encoding="utf-8"
        )
        export_json(snapshot,output/"candidate-snapshot.json")
        return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", type=Path, required=True)
    parser.add_argument("--b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(preview(args.a,args.b,args.output),sort_keys=True))


if __name__ == "__main__":
    main()
