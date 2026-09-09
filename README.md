# monad-execbench

`monad-execbench` is a contract-agnostic tool for replaying and benchmarking arbitrary EVM calls with the production Monad C++ execution engine.

The project is preparing its first pre-1.0 release. Capture, verified offline
replay, warmed direct-VM timing, and Markdown reports are implemented. Profiling
and extended benchmark modes remain planned. See the [support and release
policy](docs/releases.md) and [project specification](docs/spec.md).

## Architecture

The tool is split into three layers:

1. Foundry prepares contract deployments and ABI-encoded calls.
2. Fixture capture records the block environment and state required to replay each call.
3. The C++ runner executes fixtures through the production Monad VM and measures their performance.

No contract address, ABI, selector, or workload is compiled into the runner.

## Dependencies

Monad execution and Google Benchmark are included as pinned Git submodules
under `third_party/`. Initialize all nested dependencies after cloning:

```bash
git submodule update --init --recursive
```

The initial integration targets `MONAD_TEN` using Monad release `v0.16.2+1` at commit `aae93c5352510f09640733e58159201d3cbad063`.

Google Benchmark is pinned to release `v1.9.1`. Building it with the runner
avoids using host packages with different optimization or assertion settings.

## Platform

The C++ runner targets Linux on an x86-64-v3-compatible CPU. Release CI uses
Ubuntu 26.04, GCC 15, and libstdc++; upstream's Clang 19 support is not yet
covered by this project's release matrix. Python 3.11+ capture/report tools
are tested on Linux and macOS. See the [validated baseline](docs/releases.md#supported-baseline).

## Build

From the repository root on a supported Linux host:

```bash
CC=gcc-15 CXX=g++-15 cmake \
  -S . \
  -B build \
  -G Ninja \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/third_party/monad/category/core/toolchains/gcc-avx2.cmake"

cmake --build build --target monad-execbench --parallel
ctest --test-dir build --output-on-failure -R monad-execbench
```

The [release guide](docs/releases.md#reproduce-checks-locally) provides the
containerized dependency setup and full correctness workflow. After building,
`cmake --install build --prefix /path/to/installation --component execbench`
installs just the runner without upstream projects' install rules.

Run the VM smoke test:

```bash
./build/monad-execbench smoke --execution-env MONAD_TEN
```

Verify a portable fixture suite offline:

```bash
./build/monad-execbench verify path/to/fixture-suite
```

Verification loads the captured state into Monad's page-encoded in-memory
database, executes every case with both `InterpreterOnly` and production
`Dual` VM modes, and requires matching status, output, execution gas, logs,
and selected post-state. An account, runtime code, storage slot, or block hash
read that was not captured makes verification fail.

The bundle schema is documented in
[docs/fixture-format.md](docs/fixture-format.md).

Run a verified production-mode benchmark and write raw JSON results:

```bash
./build/monad-execbench run path/to/fixture-suite \
  --mode dual-hot \
  --repetitions 50 \
  --output results/dual-hot.json
```

The runner also supports `interpreter-hot`, case-name glob filtering, and
selected Google Benchmark options. See the
[direct-VM benchmarking guide](docs/benchmarking.md) for timing boundaries,
cache semantics, result fields, and host preparation.

## Markdown reports

After installing the Python utilities with `python -m pip install -e .`, turn
saved results into a contract-agnostic report without executing any benchmarks:

```bash
monad-execbench-report \
  --input dual=results/dual-hot.json \
  --input interpreter=results/interpreter-hot.json \
  --output results/report.md
```

Reports contain per-case gas, wall/CPU distributions, exact metadata, recorded
provenance, and measurement-quality warnings. An optional `--comparisons` JSON
manifest selects explicit baseline/candidate pairs for gas and timing ratios;
incompatible modes, fixtures, builds, or hosts cannot be silently compared.
See the [reporting guide](docs/reporting.md) for pairing, statistical conventions,
validation rules, and limitations.

## Capture utility

The Python capture utility converts generic EVM call descriptions into
portable fixture suites using a Monad-compatible local fork:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/monad-execbench-capture \
  --rpc-url http://127.0.0.1:8545 \
  --calls benchmark-calls.json \
  --block latest \
  --output fixtures/generated/example-suite
```

See [the capture guide](docs/capture.md) for the call-manifest schema, required
RPC methods, and offline verification workflow.

## Foundry integration

Consumer projects can import [`foundry/src/ExecBench.sol`](foundry/src/ExecBench.sol)
from a Forge script, register calls using ABI-encoded calldata, and write a
validated call manifest for the capture utility. Cases can carry string labels
and exact unsigned counters such as implementation names and input amounts;
the runner preserves them in the raw benchmark JSON.

The repository includes an end-to-end integration workload that deploys fresh
contracts, writes its manifest through the helper, captures state from Anvil,
verifies the portable fixture, and executes a short benchmark. See the
[Foundry workflow](docs/foundry.md) for usage and execution-environment
compatibility requirements.

## License

This project is licensed under the GNU General Public License version 3.0. See [LICENSE](LICENSE).
