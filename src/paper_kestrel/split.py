from __future__ import annotations

import argparse
import shutil
from pathlib import Path


A_DIRS = (
    "assets/",
    "locales/",
    "js/app/",
    "js/ui/",
    "js/journey/",
    "js/map/",
    "js/navigation/",
    "js/driver/",
    "js/water/",
)
B_DIRS = (
    "api/",
    "server/",
    "supabase/",
    "scripts/",
    "tests/",
    "seo/",
    "wordpress/",
    "config/",
    "data/",
    "go/",
)
A_FILES = {"index.html", "privacy.html"}
B_FILES = {"package.json", "package-lock.json"}
SKIP_NAMES = {".git", ".github", "README.md", "NOTICE.md"}


def owner(rel: str) -> str | None:
    rel = rel.replace("\\", "/").lstrip("./")
    if rel in A_FILES or any(rel.startswith(p) for p in A_DIRS):
        return "a"
    if rel in B_FILES or any(rel.startswith(p) for p in B_DIRS):
        return "b"
    if rel.startswith("js/"):
        return "b"
    return None


def iter_owned(source: Path):
    for p in source.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(source).as_posix()
        if any(part in SKIP_NAMES for part in p.relative_to(source).parts):
            continue
        side = owner(rel)
        if side:
            yield side, rel, p


def export_source(source: Path, out_a: Path, out_b: Path) -> None:
    for out in (out_a, out_b):
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
    for side, rel, src in iter_owned(source):
        dst = (out_a if side == "a" else out_b) / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def overlay(src: Path, dst: Path) -> None:
    for p in src.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(src)
        if any(part in SKIP_NAMES for part in rel.parts):
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)


def assemble(repo_a: Path, repo_b: Path, work: Path) -> None:
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    overlay(repo_a, work)
    overlay(repo_b, work)


def clean_owned(target: Path, side: str) -> None:
    for p in sorted(target.rglob("*"), reverse=True):
        if p.is_file():
            rel = p.relative_to(target).as_posix()
            if owner(rel) == side:
                p.unlink()
    for p in sorted(target.rglob("*"), reverse=True):
        if p.is_dir() and p.name not in {".git", ".github"}:
            try:
                p.rmdir()
            except OSError:
                pass


def sync_back(work: Path, repo_a: Path, repo_b: Path) -> None:
    clean_owned(repo_a, "a")
    clean_owned(repo_b, "b")
    for side, rel, src in iter_owned(work):
        dst = (repo_a if side == "a" else repo_b) / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def cli() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("export")
    e.add_argument("--source", required=True)
    e.add_argument("--a", required=True)
    e.add_argument("--b", required=True)

    a = sub.add_parser("assemble")
    a.add_argument("--a", required=True)
    a.add_argument("--b", required=True)
    a.add_argument("--work", required=True)

    s = sub.add_parser("sync")
    s.add_argument("--work", required=True)
    s.add_argument("--a", required=True)
    s.add_argument("--b", required=True)

    args = p.parse_args()
    if args.cmd == "export":
        export_source(Path(args.source).resolve(), Path(args.a).resolve(), Path(args.b).resolve())
    elif args.cmd == "assemble":
        assemble(Path(args.a).resolve(), Path(args.b).resolve(), Path(args.work).resolve())
    else:
        sync_back(Path(args.work).resolve(), Path(args.a).resolve(), Path(args.b).resolve())


if __name__ == "__main__":
    cli()
