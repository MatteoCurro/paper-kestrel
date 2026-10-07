from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Literal

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


def _safe_root() -> Path:
    return Path(os.environ.get("AGENT_WORKSPACE", "work")).resolve()


def _resolve(path: str) -> Path:
    root = _safe_root()
    target = (root / path).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Path escapes workspace")
    rel = target.relative_to(root).as_posix() if target != root else "."
    if rel == ".git" or rel.startswith(".git/"):
        raise ValueError("Git internals are not writable")
    if rel == ".github" or rel.startswith(".github/"):
        raise ValueError("Workflow files are outside the coding-agent write surface")
    return target


class PathInput(BaseModel):
    path: str = Field(..., description="Path relative to the assembled workspace")


class ReadInput(PathInput):
    start_line: int = Field(1, ge=1)
    end_line: int = Field(240, ge=1, le=2000)


class ReadFileTool(BaseTool):
    name: str = "read_file"
    description: str = "Read a bounded line range from a text file in the workspace."
    args_schema: type[BaseModel] = ReadInput

    def _run(self, path: str, start_line: int = 1, end_line: int = 240) -> str:
        target = _resolve(path)
        if not target.is_file():
            return f"NOT_FOUND: {path}"
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        end_line = min(end_line, len(lines))
        if start_line > end_line:
            return ""
        return "\n".join(f"{i}: {lines[i-1]}" for i in range(start_line, end_line + 1))


class ListInput(BaseModel):
    path: str = Field(".", description="Directory relative to workspace")
    depth: int = Field(2, ge=1, le=5)


class ListFilesTool(BaseTool):
    name: str = "list_files"
    description: str = "List files below a workspace directory with a bounded depth."
    args_schema: type[BaseModel] = ListInput

    def _run(self, path: str = ".", depth: int = 2) -> str:
        root = _resolve(path)
        if not root.exists():
            return f"NOT_FOUND: {path}"
        base_depth = len(root.parts)
        rows: list[str] = []
        for p in sorted(root.rglob("*")):
            if ".git" in p.parts:
                continue
            if len(p.parts) - base_depth > depth:
                continue
            rows.append(p.relative_to(_safe_root()).as_posix() + ("/" if p.is_dir() else ""))
            if len(rows) >= 600:
                rows.append("...TRUNCATED...")
                break
        return "\n".join(rows)


class SearchInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)
    path: str = Field(".", description="Path relative to workspace")
    max_results: int = Field(80, ge=1, le=200)


class SearchTextTool(BaseTool):
    name: str = "search_text"
    description: str = "Search repository text with ripgrep. Returns matching file names and lines."
    args_schema: type[BaseModel] = SearchInput

    def _run(self, query: str, path: str = ".", max_results: int = 80) -> str:
        target = _resolve(path)
        proc = subprocess.run(
            ["rg", "-n", "--hidden", "--glob", "!.git/**", "--glob", "!.github/**", query, str(target)],
            cwd=_safe_root(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
        lines = proc.stdout.splitlines()[:max_results]
        return "\n".join(lines) if lines else "NO_MATCHES"


class WriteInput(PathInput):
    content: str = Field(..., description="Complete UTF-8 replacement content")


class WriteFileTool(BaseTool):
    name: str = "write_file"
    description: str = "Create or fully replace a text file inside the workspace. Cannot touch Git or workflow files."
    args_schema: type[BaseModel] = WriteInput

    def _run(self, path: str, content: str) -> str:
        target = _resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"WROTE {path} ({len(content)} chars)"


class ReplaceInput(PathInput):
    old: str = Field(..., min_length=1)
    new: str
    count: int = Field(1, ge=1, le=20)


class ReplaceInFileTool(BaseTool):
    name: str = "replace_in_file"
    description: str = "Perform an exact bounded replacement in a text file. Fails if the old text is absent."
    args_schema: type[BaseModel] = ReplaceInput

    def _run(self, path: str, old: str, new: str, count: int = 1) -> str:
        target = _resolve(path)
        if not target.is_file():
            return f"NOT_FOUND: {path}"
        text = target.read_text(encoding="utf-8")
        found = text.count(old)
        if found == 0:
            return "OLD_TEXT_NOT_FOUND"
        if found < count:
            return f"ONLY_{found}_MATCHES"
        target.write_text(text.replace(old, new, count), encoding="utf-8")
        return f"REPLACED {count} occurrence(s) in {path}"


class DiffInput(BaseModel):
    max_chars: int = Field(30000, ge=2000, le=80000)


class GitDiffTool(BaseTool):
    name: str = "workspace_diff"
    description: str = "Show the current diff against the assembled baseline."
    args_schema: type[BaseModel] = DiffInput

    def _run(self, max_chars: int = 30000) -> str:
        subprocess.run(
            ["git", "add", "-N", "--", ".", ":(exclude)node_modules/**"],
            cwd=_safe_root(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
            check=False,
        )
        proc = subprocess.run(
            ["git", "diff", "--", ".", ":(exclude)node_modules/**"],
            cwd=_safe_root(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
        out = proc.stdout
        if len(out) > max_chars:
            return out[:max_chars] + "\n...DIFF TRUNCATED..."
        return out or "NO_DIFF"


class CheckInput(BaseModel):
    check: Literal["full_test", "account_focus", "diff_check", "python_compile", "single_js_test"]
    path: str | None = Field(None, description="For single_js_test, a tests/*.cjs file")


class RunChecksTool(BaseTool):
    name: str = "run_checks"
    description: str = "Run one of the allowlisted validation commands. Arbitrary shell commands are not accepted."
    args_schema: type[BaseModel] = CheckInput

    def _run(self, check: str, path: str | None = None) -> str:
        root = _safe_root()
        if check == "full_test":
            cmd = ["npm", "test"]
        elif check == "account_focus":
            cmd = [
                "bash",
                "-lc",
                "node tests/account-foundation.cjs && node tests/account-onboarding.cjs && node tests/account-sync-ui.cjs",
            ]
        elif check == "diff_check":
            cmd = ["git", "diff", "--check"]
        elif check == "python_compile":
            cmd = [
                "python3",
                "-m",
                "py_compile",
                "server/build_transit_data.py",
                "scripts/build_topocivici.py",
            ]
        elif check == "single_js_test":
            if not path or not path.startswith("tests/") or not path.endswith(".cjs"):
                return "INVALID_TEST_PATH"
            cmd = ["node", str(_resolve(path))]
        else:
            return "UNKNOWN_CHECK"
        try:
            proc = subprocess.run(
                cmd,
                cwd=root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=900,
            )
        except subprocess.TimeoutExpired:
            return json.dumps({"check": check, "returncode": 124, "output": "TIMEOUT"})
        output = proc.stdout[-20000:]
        return json.dumps({"check": check, "returncode": proc.returncode, "output": output})


def developer_tools() -> list[BaseTool]:
    return [
        ReadFileTool(),
        ListFilesTool(),
        SearchTextTool(),
        WriteFileTool(),
        ReplaceInFileTool(),
        GitDiffTool(),
        RunChecksTool(),
    ]


def reviewer_tools() -> list[BaseTool]:
    return [
        ReadFileTool(),
        ListFilesTool(),
        SearchTextTool(),
        GitDiffTool(),
        RunChecksTool(),
    ]
