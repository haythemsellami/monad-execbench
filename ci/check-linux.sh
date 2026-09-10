#!/usr/bin/env bash
set -euo pipefail

test "$(uname -s)" = Linux
test "$(uname -m)" = x86_64
for feature in avx2 bmi1 bmi2 fma; do
  if ! grep -qw "$feature" /proc/cpuinfo; then
    echo "The native runner requires an x86-64-v3 CPU; missing $feature" >&2
    exit 1
  fi
done

mkdir -p results/ci
# Keep disposable caches out of the source and dependency trees.
export XDG_CACHE_HOME="$PWD/results/ci/cache"
export FOUNDRY_DIR="$PWD/results/ci/foundry"
export SVM_HOME="$PWD/results/ci/solc"

python3 -m venv .venv
export PATH="$PWD/.venv/bin:$PATH"
python -m pip install -e '.[dev]'
python scripts/check_release.py --check-submodules
bash ci/check-python.sh
forge --version
anvil --version
expected_foundry="$(python -c 'import json; print(json.load(open("release.json"))["foundry_version"].removeprefix("v"))')"
forge --version | grep -Fx "forge Version: $expected_foundry"
anvil --version | grep -Fx "anvil Version: $expected_foundry"
forge fmt --check --root foundry
forge test --root foundry -vv

CC=gcc-15 CXX=g++-15 cmake -S . -B build -G Ninja \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/third_party/monad/category/core/toolchains/gcc-avx2.cmake"
cmake --build build --target monad-execbench --parallel "${EXECBENCH_BUILD_JOBS:-2}"
ctest --test-dir build --output-on-failure --no-tests=error -R '^monad-execbench-'
cmake --install build --prefix "$PWD/results/ci/install" --component execbench
runner="$PWD/results/ci/install/bin/monad-execbench"
"$runner" --version
"$runner" smoke --execution-env MONAD_TEN
CC=gcc-15 CXX=g++-15 cmake -S . -B build-diagnostics -G Ninja \
  -DMONAD_EXECBENCH_DIAGNOSTICS=ON -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/third_party/monad/category/core/toolchains/gcc-avx2.cmake"
cmake --build build-diagnostics --target monad-execbench --parallel "${EXECBENCH_BUILD_JOBS:-2}"
cmake --install build-diagnostics --prefix "$PWD/results/ci/install" --component execbench
diagnostics="$PWD/results/ci/install/bin/monad-execbench-diagnostics"
"$diagnostics" --version
python tests/attribution/native_checks.py --diagnostics "$diagnostics"
python tests/capture/anvil_roundtrip.py --verifier "$runner" --diagnostics "$diagnostics" --output results/ci/roundtrip

python -m pip freeze > results/ci/python-packages.txt
dpkg-query -W > results/ci/system-packages.txt
ldd "$runner" > results/ci/native-libraries.txt
git rev-parse HEAD > results/ci/runner-revision.txt
git submodule status --recursive > results/ci/submodule-revisions.txt
