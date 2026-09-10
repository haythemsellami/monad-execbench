from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SMOKE = """
import json
import sys
from importlib import metadata
from importlib.resources import files
from pathlib import Path
import monad_execbench_capture as capture
import monad_execbench_report as report
import monad_execbench_attribution as attribution
from monad_execbench_capture.cli import detect_monad_commit
expected = json.loads(sys.argv[1])
assert metadata.version('monad-execbench-capture') == expected['version']
assert capture.__version__ == report.__version__ == attribution.__version__ == expected['version']
assert detect_monad_commit() == expected['monad_commit']
schema = files('monad_execbench_capture').joinpath('schema/calls-v1.json')
assert json.loads(schema.read_text())['properties']['schema']['const'] == 'monad-execbench/calls-v1'
for package in (capture, report, attribution):
    assert Path(package.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
print('isolated package versions, resources, and dependency pin verified')
"""


def run(arguments: list[str | Path], *, cwd: Path) -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    subprocess.run(
        [str(value) for value in arguments], cwd=cwd, env=environment, check=True
    )


def verify_install(wheel: Path, directory: Path, release: dict) -> None:
    venv.EnvBuilder(with_pip=True).create(directory / "venv")
    python = directory / "venv/bin/python"
    run([python, "-m", "pip", "install", wheel], cwd=directory)
    run([python, "-I", "-c", SMOKE, json.dumps(release)], cwd=directory)
    for name in (
        "monad-execbench-capture",
        "monad-execbench-report",
        "monad-execbench-attribute",
    ):
        executable = directory / "venv/bin" / name
        run([executable, "--version"], cwd=directory)
        run([executable, "--help"], cwd=directory)
    # Tests live in the checkout, but installed packages must come from the
    # isolated venv: no editable installs or source-package PYTHONPATH.
    for suite in ("capture", "report", "attribution"):
        run(
            [
                python,
                "-I",
                "-m",
                "unittest",
                "discover",
                "-s",
                ROOT / "tests" / suite,
                "-q",
            ],
            cwd=directory,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build and verify wheel and sdist installations outside the checkout"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    arguments = parser.parse_args()
    release = json.loads((ROOT / "release.json").read_text())
    with tempfile.TemporaryDirectory(prefix="execbench-packaging-") as temporary:
        work = Path(temporary)
        built = work / "built"
        run([sys.executable, "-m", "build", "--outdir", built, ROOT], cwd=work)
        wheels, sources = list(built.glob("*.whl")), list(built.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sources) != 1:
            raise RuntimeError("expected exactly one wheel and one source distribution")
        run([sys.executable, "-m", "twine", "check", *wheels, *sources], cwd=work)
        with tarfile.open(sources[0]) as archive:
            names = archive.getnames()
            if any(
                "/.git/" in name or "/third_party/" in name or "/results/" in name
                for name in names
            ):
                raise RuntimeError(
                    "Python source distribution includes repository/build state"
                )
        # Rebuild from the actual source archive, not from the working tree.
        rebuilt = work / "from-sdist"
        run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--wheel-dir",
                rebuilt,
                sources[0],
            ],
            cwd=work,
        )
        rebuilt_wheels = list(rebuilt.glob("*.whl"))
        if len(rebuilt_wheels) != 1:
            raise RuntimeError("source distribution did not rebuild exactly one wheel")
        for name, wheel in (("wheel", wheels[0]), ("sdist", rebuilt_wheels[0])):
            verify_install(wheel, work / name, release)
        arguments.output.mkdir(parents=True, exist_ok=True)
        for artifact in (*wheels, *sources):
            shutil.copy2(artifact, arguments.output / artifact.name)
    print(f"wheel and sdist installations passed: {arguments.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
