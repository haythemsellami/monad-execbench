from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
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
            "capture/monad_execbench_capture/capture.py",
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
        version = self.release["version"]
        self.assertEqual(self.check(tag=f"v{version}")["version"], version)
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
                path.write_text(original.replace(self.release["version"], "9.0.0"))
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
        path.write_text(
            path.read_text().replace(self.release["foundry_version"], "v0.0.0")
        )
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

    def test_dirty_release_checkout_is_rejected(self):
        original_git = self.git
        self.git = lambda root, *args: (
            " M README.md"
            if args == ("status", "--porcelain")
            else original_git(root, *args)
        )
        with self.assertRaisesRegex(ValueError, "clean checkout"):
            self.check(check_clean=True)

    def test_environment_and_python_matrix_drift_are_rejected(self):
        path = self.root / "release.json"
        for key, value in (
            ("execution_env", "MONAD_NINE"),
            ("python_versions_tested", ["3.11", "3.13"]),
        ):
            with self.subTest(key=key):
                path.write_text(json.dumps({**self.release, key: value}))
                with self.assertRaisesRegex(ValueError, "disagrees"):
                    self.check()

    def test_release_manifest_checksums_every_asset(self):
        spec = importlib.util.spec_from_file_location(
            "prepare_release", ROOT / "scripts/prepare_release.py"
        )
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"check_release": checker}):
            spec.loader.exec_module(module)
        assets = self.root / "assets"
        assets.mkdir()
        (assets / "package.whl").write_bytes(b"wheel")
        (assets / "package.tar.gz").write_bytes(b"source")
        module.write_manifest(assets, self.release, "a" * 40, " pinned dependency")
        lines = (assets / "SHA256SUMS").read_text().splitlines()
        self.assertEqual(len(lines), 3)
        for line in lines:
            digest, name = line.split("  ")
            self.assertEqual(
                digest, hashlib.sha256((assets / name).read_bytes()).hexdigest()
            )
        manifest = json.loads((assets / "release-manifest.json").read_text())
        self.assertEqual(manifest["source_commit"], "a" * 40)


if __name__ == "__main__":
    unittest.main()
