# Direct-VM benchmarking

`monad-execbench run` measures fixture calls directly through the production
Monad VM. It accepts the same portable fixture suites as `verify` and performs
no RPC, filesystem, or fixture parsing work inside a timed iteration.

## Build

Use an optimized build with debug symbols on a Linux x86-64-v3 host:

```bash
CC=gcc-15 CXX=g++-15 cmake \
  -S . \
  -B build \
  -G Ninja \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/third_party/monad/category/core/toolchains/gcc-avx2.cmake"

cmake --build build --target monad-execbench --parallel
```

Google Benchmark is built from the pinned `third_party/benchmark` submodule so
the measurement framework does not depend on a host package or a debug build.

## Run

The headline production-mode run is:

```bash
./build/monad-execbench run fixtures/example-suite \
  --mode dual-hot \
  --repetitions 50 \
  --output results/dual-hot.json
```

The diagnostic interpreter run is:

```bash
./build/monad-execbench run fixtures/example-suite \
  --mode interpreter-hot \
  --repetitions 50 \
  --output results/interpreter-hot.json
```

`dual-hot` is the default mode. It uses `VM::Dual` and synchronously populates
the decoded-code and native-code caches for every captured runtime before any
sample is taken. `interpreter-hot` uses `VM::InterpreterOnly` and primes the
decoded/intermediate-code cache without producing native entry points.

Use a glob to select cases by their manifest names:

```bash
./build/monad-execbench run fixtures/example-suite \
  --filter 'implementation-b/*' \
  --output results/implementation-b.json
```

`*` matches any sequence and `?` matches one character. Filtering does not
weaken fixture validation: the complete suite is verified before any selected
case is measured.

Additional Google Benchmark options may follow `--`. For example, this is a
short smoke run rather than a result suitable for comparison:

```bash
./build/monad-execbench run fixtures/example-suite \
  --repetitions 2 \
  --output /tmp/smoke.json \
  -- --benchmark_min_time=0.001s
```

Output selection, repetition count, case filtering, JSON format, and randomized
interleaving are owned by `monad-execbench` and cannot be overridden through
passthrough arguments.

## Correctness and timing boundary

Every run first executes every fixture case with warmed `InterpreterOnly` and
`Dual` sessions. Status, output, execution gas, logs, selected post-state, and
captured-state completeness must agree before benchmark registration begins.

The benchmark session then builds one immutable in-memory base state and one
VM with a persistent hot code cache. Each measured iteration:

1. Pauses timing and creates fresh `BlockState`, `State`, transaction context,
   host, access-list warming, and message memory.
2. Resumes timing immediately before `execute_call_message`, which includes the
   root VM call and every nested contract call.
3. Pauses timing immediately after execution.
4. Checks status, output, execution gas, logs, and configured post-state.
5. Discards the mutated transaction state and resumes timing for the benchmark
   loop boundary.

State changes therefore cannot leak between repetitions, while decoded and
native code remain cached according to the selected hot mode. Fixture loading,
base-state construction, cache priming, state reset, correctness checks, and
JSON serialization are excluded from reported times.

## Results

The JSON file contains every raw repetition plus Google Benchmark aggregates.
The runner requests randomized interleaving across registered cases to reduce
time-order bias.

The report context records:

- Runner version and source revision.
- Pinned Monad revision.
- Build type and compiler.
- Fixture schema and directory.
- Execution environment, block number, and block hash.
- Mode, case filter, repetition count, CPU topology, and benchmark-library
  version.

Each case records real time, process CPU time, iterations, execution gas,
return-data bytes, log count, and success or revert status.

For publishable results, pin the process to a physical CPU, keep competing load
off that core, use a stable CPU-frequency policy, retain the raw JSON, and treat
Google Benchmark environment warnings as reasons to rerun rather than as
reportable measurements.
