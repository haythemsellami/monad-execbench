from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from check_release import ROOT, check_release, git


def write_manifest(
    directory: Path, release: dict, revision: str, dependencies: str
) -> None:
    manifest = {
        "release": release,
        "source_commit": revision,
        "submodules": dependencies.splitlines(),
        "python_build_version": sys.version,
        "artifact_scope": "Python wheel/sdist, Foundry helper, and call schema; native runner is built from a recursive Git checkout",
    }
    (directory / "release-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    checksums = []
    for path in sorted(directory.iterdir()):
        if path.is_file():
            checksums.append(
                f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
            )
    (directory / "SHA256SUMS").write_text("\n".join(checksums) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare checked release candidates without creating a tag or publishing"
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="new artifact directory, preferably under dist/",
    )
    arguments = parser.parse_args()
    output = arguments.output.absolute()
    try:
        if output.exists() or output.is_symlink():
            raise ValueError("output already exists; choose a new directory")
        release = check_release(ROOT, check_submodules=True, check_clean=True)
        revision = git(ROOT, "rev-parse", "HEAD")
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".execbench-release-", dir=output.parent
        ) as temporary:
            stage = Path(temporary) / "artifacts"
            subprocess.run(
                [
                    sys.executable,
                    ROOT / "tests/packaging/check_distributions.py",
                    "--output",
                    stage,
                ],
                check=True,
            )
            shutil.copyfile(ROOT / "foundry/src/ExecBench.sol", stage / "ExecBench.sol")
            shutil.copyfile(ROOT / "LICENSE", stage / "LICENSE")
            shutil.copyfile(
                ROOT / "capture/monad_execbench_capture/schema/calls-v1.json",
                stage / "calls-v1.json",
            )
            check_release(ROOT, check_submodules=True, check_clean=True)
            if git(ROOT, "rev-parse", "HEAD") != revision:
                raise ValueError("source revision changed during release preparation")
            write_manifest(
                stage,
                release,
                revision,
                git(ROOT, "submodule", "status", "--recursive"),
            )
            if output.exists() or output.is_symlink():
                raise ValueError(
                    "output appeared during preparation; choose a new directory"
                )
            stage.rename(output)
        print(f"release candidates={output}")
        print(
            "Nothing was tagged, uploaded, or published. Require passing correctness CI for this source commit before release."
        )
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"release preparation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
