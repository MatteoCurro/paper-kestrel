"""Safe replay against isolated Git worktrees, never remote repositories."""
import copy
import subprocess
import tempfile
import unittest
from pathlib import Path

from paper_kestrel.candidate_snapshot import capture, restore, SnapshotConflict


def git(work, *argv):
    return subprocess.run(["git","-C",str(work),*argv],
                          check=True,capture_output=True).stdout.decode().strip()


def init(work: Path):
    git(work,"init","-q")
    git(work,"config","user.name","TSAND test")
    git(work,"config","user.email","test@example.invalid")
    (work/"index.html").write_text("<p>before</p>",encoding="utf-8")
    (work/"binary.bin").write_bytes(bytes([0, 3, 255])*100)
    git(work,"add","-A")
    git(work,"commit","-qm","baseline")


class CandidateSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.root=Path(self.folder.name)
        self.first=self.root/"first"
        self.first.mkdir()
        init(self.first)

    def tearDown(self):
        self.folder.cleanup()

    def another(self):
        second=self.root/"second"
        second.mkdir()
        init(second)
        return second

    def test_text_binary_delete_and_new_file_restore_to_identical_git_tree(self):
        (self.first/"index.html").write_text("<p>after</p>",encoding="utf-8")
        (self.first/"binary.bin").write_bytes(bytes([0, 4, 254])*100)
        (self.first/"new.txt").write_text("candidate")
        snapshot=capture(self.first)
        other=self.another()
        self.assertEqual(restore(other,snapshot),snapshot["candidate_tree"])
        self.assertEqual((other/"index.html").read_text(),"<p>after</p>")
        self.assertEqual((other/"binary.bin").read_bytes(),bytes([0, 4, 254])*100)
        self.assertEqual((other/"new.txt").read_text(),"candidate")

    def test_delete_can_be_replayed(self):
        (self.first/"index.html").unlink()
        snapshot=capture(self.first)
        other=self.another()
        restore(other,snapshot)
        self.assertFalse((other/"index.html").exists())

    def test_changed_baseline_rejected(self):
        (self.first/"index.html").write_text("changed")
        snapshot=capture(self.first)
        other=self.another()
        (other/"index.html").write_text("unrelated")
        git(other,"add","-A")
        git(other,"commit","-qm","another baseline")
        with self.assertRaises(SnapshotConflict):
            restore(other,snapshot)

    def test_tampered_or_dirty_workspace_rejected(self):
        (self.first/"index.html").write_text("changed")
        snapshot=capture(self.first)
        other=self.another()
        corrupt=copy.deepcopy(snapshot)
        corrupt["patch_sha256"]="f"*64
        with self.assertRaises(SnapshotConflict):
            restore(other,corrupt)
        (other/"unexpected.txt").write_text("untracked")
        with self.assertRaises(SnapshotConflict):
            restore(other,snapshot)

    def test_empty_patch_roundtrip(self):
        snapshot=capture(self.first)
        other=self.another()
        self.assertEqual(restore(other,snapshot),snapshot["candidate_tree"])


if __name__=="__main__":
    unittest.main()
