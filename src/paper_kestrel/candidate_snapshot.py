"""Content-addressed candidate patch snapshots for ephemeral GitHub runners.

The archive contains *only* a Git binary patch plus exact source/candidate
Git tree object IDs. It never stores a whole repository, credentials, or .git.
It may be applied only to a clean workspace with the exact original tree.
This preserves committed candidate work; interrupted work stays quarantined.
"""
from __future__ import annotations
import base64
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


class SnapshotConflict(RuntimeError):
    pass


def _git(work: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(work), *args], input=input_bytes,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        raise SnapshotConflict(
            "Git candidate verification failed: " +
            result.stderr.decode("utf-8", errors="replace")[:260]
        )
    return result.stdout


def _tree(work: Path, revision: str = "HEAD") -> str:
    return _git(work, "rev-parse", "--verify", revision + "^{tree}").decode().strip()


def _clean(work: Path) -> None:
    if _git(work, "status", "--porcelain", "--untracked-files=all").strip():
        raise SnapshotConflict("Refusing restoration into a dirty workspace")


def capture(workspace: Path) -> dict[str, Any]:
    """Commit-independent immutable snapshot; caller keeps the JSON as artifact.

    The method stages the candidate in the ephemeral work Git index. It neither
    commits nor pushes, and MUST NOT be used in a non-ephemeral user checkout.
    """
    work = Path(workspace).resolve()
    source = _tree(work)
    _git(work, "add", "-A", "--")
    candidate = _git(work, "write-tree").decode().strip()
    diff = _git(work, "diff", "--cached", "--binary", "--full-index", "HEAD", "--")
    return {
        "format": "paper-kestrel-candidate-v1",
        "source_tree": source,
        "candidate_tree": candidate,
        "patch_sha256": hashlib.sha256(diff).hexdigest(),
        "patch_base64": base64.b64encode(diff).decode("ascii"),
    }


def restore(workspace: Path, snapshot: dict[str, Any]) -> str:
    """Apply an exact verified candidate patch or fail without touching files."""
    work = Path(workspace).resolve()
    _clean(work)
    if snapshot.get("format") != "paper-kestrel-candidate-v1":
        raise SnapshotConflict("Unrecognized snapshot format")
    source = snapshot.get("source_tree")
    expected = snapshot.get("candidate_tree")
    patch_sha = snapshot.get("patch_sha256")
    if (not all(isinstance(v, str) and len(v) in (40, 64)
                for v in (source, expected)) or
            not isinstance(patch_sha, str) or len(patch_sha) != 64):
        raise SnapshotConflict("Incomplete snapshot integrity metadata")
    if _tree(work) != source:
        raise SnapshotConflict("Baseline tree changed: cannot replay candidate")
    try:
        diff = base64.b64decode(snapshot["patch_base64"], validate=True)
    except (KeyError, ValueError, TypeError) as exc:
        raise SnapshotConflict("Damaged binary patch encoding") from exc
    if hashlib.sha256(diff).hexdigest() != patch_sha:
        raise SnapshotConflict("Candidate patch digest mismatch")
    # The check is prior to filesystem mutation. Target hash is verified after.
    _git(work, "apply", "--check", "--index", "--binary", "-", input_bytes=diff)
    _git(work, "apply", "--index", "--binary", "-", input_bytes=diff)
    actual = _git(work, "write-tree").decode().strip()
    if actual != expected:
        raise SnapshotConflict("Candidate tree differs after patch restoration")
    return actual


def export_json(snapshot: dict[str, Any], filename: Path) -> None:
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def import_json(filename: Path) -> dict[str, Any]:
    data = json.loads(Path(filename).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SnapshotConflict("Snapshot must be a JSON object")
    return data
