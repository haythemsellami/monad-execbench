from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments], check=True, capture_output=True, text=True
    ).stdout.strip()


def check_release(
    root: Path,
    *,
    check_submodules: bool = False,
    check_clean: bool = False,
    tag: str | None = None,
) -> dict:
    release = json.loads((root / "release.json").read_text())
    version = release["version"]
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None:
        raise ValueError("release.version must be a stable major.minor.patch version")
    if tag is not None and tag != f"v{version}":
        raise ValueError(f"release tag must be v{version}, got {tag}")
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    if project["version"] != version:
        raise ValueError("Python distribution version disagrees with release.json")
    cmake = (root / "CMakeLists.txt").read_text()
    if f"project(monad_execbench VERSION {version} LANGUAGES C CXX ASM)" not in cmake:
        raise ValueError("CMake version disagrees with release.json")
    for package in (
        "capture/monad_execbench_capture",
        "analysis/monad_execbench_report",
    ):
        tree = ast.parse((root / package / "__init__.py").read_text())
        versions = [
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__version__"
                for target in node.targets
            )
        ]
        if versions != [version]:
            raise ValueError(f"{package} version disagrees with release.json")
    pin = (
        (root / "capture/monad_execbench_capture/pinned-monad.txt").read_text().strip()
    )
    if pin != release["monad_commit"]:
        raise ValueError("packaged Monad pin disagrees with release.json")
    for dependency in ("monad", "benchmark"):
        expected = release[f"{dependency}_commit"]
        if re.fullmatch(r"[0-9a-f]{40}", expected) is None:
            raise ValueError(f"invalid {dependency} revision")
        fields = git(root, "ls-tree", "HEAD", f"third_party/{dependency}").split()
        if len(fields) != 4 or fields[:3] != ["160000", "commit", expected]:
            raise ValueError(f"{dependency} gitlink disagrees with release.json")
    workflow = (root / ".github/workflows/ci.yml").read_text()
    foundry_versions = re.findall(r"version: (v[0-9.]+)", workflow)
    if not foundry_versions or any(
        value != release["foundry_version"] for value in foundry_versions
    ):
        raise ValueError("CI Foundry versions disagree with release.json")
    if check_submodules:
        # Keep the leading status prefix; '+'/'-'/'U' are not valid release inputs.
        status = subprocess.run(
            ["git", "-C", str(root), "submodule", "status", "--recursive"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        if not status or any(not line.startswith(" ") for line in status.splitlines()):
            raise ValueError(
                "submodules must be initialized at their recorded revisions"
            )
        for line in status.splitlines():
            path = root / line.split()[1]
            if git(path, "status", "--porcelain"):
                raise ValueError(f"dirty dependency checkout: {path}")
    if check_clean and git(root, "status", "--porcelain"):
        raise ValueError("release preparation requires a clean checkout")
    return release


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check release versions and pinned dependencies without publishing"
    )
    parser.add_argument("--check-submodules", action="store_true")
    parser.add_argument("--check-clean", action="store_true")
    parser.add_argument("--tag")
    arguments = parser.parse_args()
    try:
        release = check_release(
            ROOT,
            check_submodules=arguments.check_submodules,
            check_clean=arguments.check_clean,
            tag=arguments.tag,
        )
        print(
            f"release checks passed: {release['version']} / {release['execution_env']}"
        )
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"release checks failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
