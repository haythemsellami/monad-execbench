from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWED = {
    "ci/Dockerfile",
    "third_party/monad/scripts/ubuntu-build/install-boost.sh",
    "third_party/monad/scripts/ubuntu-build/install-deps.sh",
}
EXCLUDED = {
    ".env",
    ".git/config",
    "README.md",
    "ci/check-linux.sh",
    "third_party/benchmark/CMakeLists.txt",
    "third_party/monad/README.md",
    "third_party/monad/.git",
    "third_party/monad/category/vm/vm.cpp",
    "third_party/monad/scripts/other.sh",
    "third_party/monad/scripts/ubuntu-build/other.sh",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Docker's context allowlist using synthetic files"
    )
    parser.add_argument("--dockerignore", type=Path, default=ROOT / ".dockerignore")
    arguments = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="execbench-docker-context-") as temporary:
        work = Path(temporary)
        context = work / "context"
        output = work / "output"
        for name in sorted(ALLOWED | EXCLUDED):
            path = context / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"synthetic fixture: {name}\n", encoding="utf-8")
        shutil.copyfile(arguments.dockerignore, context / ".dockerignore")
        # COPY everything so BuildKit's selective transfers cannot hide overly
        # broad exceptions. No actual repository data or base image is needed.
        subprocess.run(
            [
                "docker",
                "build",
                "--progress=plain",
                "--file",
                "-",
                "--output",
                f"type=local,dest={output}",
                context,
            ],
            input="FROM scratch\nCOPY . /\n",
            text=True,
            check=True,
        )
        actual = {
            path.relative_to(output).as_posix()
            for path in output.rglob("*")
            if path.is_file()
        }
        if actual != ALLOWED:
            raise RuntimeError(
                f"unexpected build context: extra={sorted(actual - ALLOWED)}, "
                f"missing={sorted(ALLOWED - actual)}"
            )
    print("Docker context allowlist passed: only the three required files included")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
