# monad-execbench

`monad-execbench` is a contract-agnostic tool for replaying and benchmarking arbitrary EVM calls with the production Monad C++ execution engine.

The project is under active development. The implementation is guided by [the project specification](docs/spec.md).

## Architecture

The tool is split into three layers:

1. Foundry prepares contract deployments and ABI-encoded calls.
2. Fixture capture records the block environment and state required to replay each call.
3. The C++ runner executes fixtures through the production Monad VM and measures their performance.

No contract address, ABI, selector, or workload is compiled into the runner.

## Monad dependency

Monad execution is included as a pinned Git submodule under `third_party/monad`. Initialize all nested dependencies after cloning:

```bash
git submodule update --init --recursive
```

The initial integration targets `MONAD_TEN` using Monad release `v0.16.2+1` at commit `aae93c5352510f09640733e58159201d3cbad063`.

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

The first milestone provides a VM smoke test:

```bash
./build/monad-execbench smoke --execution-env MONAD_TEN
```

## License

This project is licensed under the GNU General Public License version 3.0. See [LICENSE](LICENSE).
