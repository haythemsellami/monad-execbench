from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "check_release", ROOT / "scripts/check_release.py"
)
assert spec is not None and spec.loader is not None
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in (
            "release.json",
            "pyproject.toml",
            "CMakeLists.txt",
            ".github/workflows/ci.yml",
            "capture/monad_execbench_capture/__init__.py",
            "capture/monad_execbench_capture/pinned-monad.txt",
            "analysis/monad_execbench_report/__init__.py",
        ):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        self.release = json.loads((self.root / "release.json").read_text())

    def git(self, root, *arguments):
        if arguments[:2] == ("ls-tree", "HEAD"):
            dependency = arguments[2].split("/")[-1]
            return f"160000 commit {self.release[dependency + '_commit']}\tthird_party/{dependency}"
        if arguments == ("status", "--porcelain"):
            return ""
        raise AssertionError(arguments)

    def check(self, **kwargs):
        with patch.object(checker, "git", side_effect=self.git):
            return checker.check_release(self.root, **kwargs)

    def test_matching_versions_and_release_tag(self):
        self.assertEqual(self.check(tag="v0.1.0")["version"], "0.1.0")
        with self.assertRaisesRegex(ValueError, "release tag"):
            self.check(tag="v9.0.0")

    def test_version_drift_is_rejected(self):
        for name in (
            "CMakeLists.txt",
            "pyproject.toml",
            "capture/monad_execbench_capture/__init__.py",
            "analysis/monad_execbench_report/__init__.py",
        ):
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_text()
                path.write_text(original.replace("0.1.0", "9.0.0"))
                with self.assertRaisesRegex(ValueError, "version disagrees"):
                    self.check()
                path.write_text(original)

    def test_dependency_pin_and_gitlink_drift_are_rejected(self):
        path = self.root / "capture/monad_execbench_capture/pinned-monad.txt"
        original = path.read_text()
        path.write_text("a" * 40)
        with self.assertRaisesRegex(ValueError, "packaged Monad pin"):
            self.check()
        path.write_text(original)
        with (
            patch.object(
                checker,
                "git",
                return_value="160000 commit " + "a" * 40 + "\tthird_party/monad",
            ),
            self.assertRaisesRegex(ValueError, "gitlink disagrees"),
        ):
            checker.check_release(self.root)

    def test_foundry_version_drift_is_rejected(self):
        path = self.root / ".github/workflows/ci.yml"
        path.write_text(path.read_text().replace("v1.8.1", "v1.8.0"))
        with self.assertRaisesRegex(ValueError, "Foundry versions"):
            self.check()

    def test_incomplete_and_dirty_dependencies_are_rejected(self):
        for prefix in ("-", "+", "U"):
            with self.subTest(prefix=prefix):
                result = subprocess.CompletedProcess(
                    [], 0, stdout=f"{prefix}{'a' * 40} third_party/monad\n"
                )
                with (
                    patch.object(checker.subprocess, "run", return_value=result),
                    self.assertRaisesRegex(ValueError, "initialized"),
                ):
                    self.check(check_submodules=True)
        result = subprocess.CompletedProcess(
            [], 0, stdout=f" {'a' * 40} third_party/monad\n"
        )
        with patch.object(checker.subprocess, "run", return_value=result):
            original_git = self.git
            self.git = lambda root, *args: (
                " M source.cpp"
                if args == ("status", "--porcelain")
                else original_git(root, *args)
            )
            with self.assertRaisesRegex(ValueError, "dirty dependency"):
                self.check(check_submodules=True)


if __name__ == "__main__":
    unittest.main()
