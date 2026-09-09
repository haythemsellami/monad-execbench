# Release and support policy

Version `0.1.0` is the first release candidate for the verified, warmed
direct-VM workflow. Merging release preparation does not publish a release.
Publication is a separate maintainer action after the exact source commit has
passed correctness CI. This is a pre-1.0 tool: schema/CLI changes must be
documented, and consumers should pin a tag or commit and keep their raw data.

## Supported baseline

| Component | Release baseline |
| --- | --- |
| Native runner | Linux x86-64-v3; CI uses an Ubuntu 26.04 container |
| Native compiler | GCC 15, libstdc++, C++23 |
| Build tools | CMake 3.27+, Ninja; `RelWithDebInfo`, Haswell/AVX2 toolchain |
| Python utilities | Python 3.11+; CI tests 3.11 and 3.14 on Linux and macOS |
| Reference node and helper tests | Foundry v1.8.1; Solidity 0.8.26 |
| Execution environment | `MONAD_TEN`, explicitly selected for Anvil |
| VM modes | `dual-hot`, `interpreter-hot` |
| Monad and Google Benchmark | Exact Git revisions in `release.json` and submodules |

Upstream also supports Clang 19 with libstdc++; it is not part of this
release's validated compiler matrix. macOS is supported for capture/reporting
and Foundry preparation, not the native C++ runner. Windows, native ARM
execution, other execution environments, and cold mode are not validated.

The Docker base image and action implementations are pinned by digest/commit,
and Foundry is pinned by release. Apt patch revisions and transitive Python
packages can change: these builds are not claimed to be bit-reproducible.
The Linux job retains installed system/Python package versions, native library
dependencies, source revisions, and synthetic replay artifacts for diagnosis.

## Correctness CI

The `Correctness` workflow runs on PRs, pushes to `main`, and manual dispatch:

- **Python matrix:** lint/formatting, capture/report/release tests, version and
  dependency-pin consistency, wheel/source-archive builds, metadata validation,
  and clean installed-package tests outside the source checkout.
- **Foundry helper:** formatting and Solidity unit tests with a pinned toolchain.
- **Linux C++ and end-to-end replay:** build in an unprivileged container,
  run only the project's CTest tests, install the runner component, then exercise
  local Anvil → Foundry helper → capture → two-mode verification → both hot
  benchmark modes → Markdown reporting. No archive RPC or chain credentials
  are required; only synthetic local contracts are used.
- **Release readiness:** fail unless every preceding job succeeds. Configure
  this as a required branch-protection check; the workflow itself does not
  change repository settings or publish artifacts as a release.

CI uses small benchmark repetitions to check behavior and output integrity,
not speed. It has no timing thresholds and must not be used as a performance
baseline. Use controlled hardware for performance regressions separately.
The workflow runs on hosted machines, never a persistent self-hosted runner
for untrusted PR code, and uses read-only repository permissions with no
publishing credentials.

## Reproduce checks locally

Python checks and isolated installation tests:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
PATH="$PWD/.venv/bin:$PATH" bash ci/check-python.sh
.venv/bin/python tests/packaging/check_distributions.py
```

The native check requires Linux, Docker, initialized submodules, and Foundry
v1.8.1 binaries on `PATH`. Run from a regular clone, not a
worktree whose `.git` pointer points outside the container mount:

```bash
git submodule update --init --recursive
bash ci/stage-foundry.sh
docker build --tag execbench-ci --file ci/Dockerfile \
  --build-arg EXECBENCH_UID="$(id -u)" \
  --build-arg EXECBENCH_GID="$(id -g)" .
docker run --rm \
  --mount "type=bind,src=$PWD,dst=/work" \
  --mount "type=bind,src=$PWD/results/ci/foundry-bin,dst=/opt/foundry,readonly" \
  --env EXECBENCH_BUILD_JOBS=2 \
  execbench-ci bash ci/check-linux.sh
```

Use a fresh checkout for a clean-build test. The roundtrip artifacts go under
`results/ci/roundtrip`; that destination must be new. For a native host with
the same system packages, `bash ci/check-linux.sh` runs without Docker.
No privileged container or relaxed seccomp profile is required by this workflow.

## Installation from a release

The initial distribution is source-based for the native runner. Clone the
selected release recursively and follow the [build guide](../README.md#build):

```bash
git clone --branch v0.1.0 --recurse-submodules \
  https://github.com/haythemsellami/monad-execbench.git
cd monad-execbench
```

This command requires that the tag has actually been published. GitHub's
automatic source ZIP/tarball and the Python source distribution do **not**
contain all native submodules and are not standalone C++ source bundles.
No portable native-binary compatibility promise is made for this release.

After building, install only the project's executable, not every upstream
dependency's install target:

```bash
cmake --install build --prefix /path/to/installation --component execbench
/path/to/installation/bin/monad-execbench --version
/path/to/installation/bin/monad-execbench smoke --execution-env MONAD_TEN
```

Python wheel/source-archive assets provide both `monad-execbench-capture` and
`monad-execbench-report`. The distribution retains its existing name,
`monad-execbench-capture`; it is not yet promised to be published on PyPI.
Install a verified downloaded wheel into a virtual environment with
`python -m pip install /path/to/monad_execbench_capture-0.1.0-py3-none-any.whl`.
The wheel includes the call schema and expected Monad revision and does not
require Git or a native checkout just to capture fixtures.

## Prepare and publish

1. Review/merge the release PR and require a successful `Release readiness`
   check for the exact `main` commit being released. Review the retained native
   and packaging artifacts; a successful Python build alone is insufficient.
2. In a clean recursive clone of that commit, install development dependencies
   and run `python scripts/check_release.py --check-submodules --check-clean
   --tag v0.1.0`. Keep version declarations, dependency pins, CI Foundry version,
   documentation, and release notes consistent when preparing later versions.
3. Run `python scripts/prepare_release.py --output dist/release-v0.1.0` from
   the prepared virtual environment. It requires clean source/dependencies,
   rebuilds and tests Python wheel and source-archive installations, and creates
   the helper, schema, release manifest, and `SHA256SUMS` in a new directory.
   It does not query CI, create tags, upload, or publish anything.
4. Verify checksums, review the manifest's source commit and dependency pins,
   and ensure they match the passing CI commit. Candidate files are not signed;
   checksums detect changes, not authorship. Keep provenance with downloaded files.
5. Only with publication approval, create an annotated `v0.1.0` tag at that
   checked commit and publish a GitHub release with these assets and reviewed
   release notes. Do not move an already published tag to different code.

Release candidates contain the Python wheel/sdist, `ExecBench.sol`,
`calls-v1.json`, `LICENSE`, `release-manifest.json`, and `SHA256SUMS`. Native binary
redistribution, vendored C++ source bundles, package-index publication, and
automated signing are future distribution work, not implicit CI side effects.

## Remaining capabilities

This release supports capture, offline correctness replay, warmed direct-VM
timing, and explicit Markdown comparisons. It does not include execution-scoped
hardware profiling, flamegraphs, opcode/call-frame/source attribution, cold-code
measurements, transaction/block benchmarking, or automated performance gates.
Those remain separate feature work, as described in the [specification](spec.md).
