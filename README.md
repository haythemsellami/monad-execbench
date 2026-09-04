# monad-execbench

`monad-execbench` is a contract-agnostic tool for replaying and benchmarking arbitrary EVM calls with the production Monad C++ execution engine.

The project is under active development. The implementation is guided by [the project specification](docs/spec.md).

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

The C++ runner targets Linux on an x86-64-v3-compatible CPU. Building the Monad execution dependency requires the compiler and system packages documented by the pinned Monad source. The supported compiler baseline is GCC 15 or Clang 19.

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

## License

This project is licensed under the GNU General Public License version 3.0. See [LICENSE](LICENSE).
