cmake_minimum_required(VERSION 3.27)

project(monad_execbench VERSION 0.1.0 LANGUAGES C CXX ASM)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(MONAD_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third_party/monad")
set(BENCHMARK_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third_party/benchmark")

if(NOT EXISTS "${BENCHMARK_SOURCE_DIR}/CMakeLists.txt")
  message(
    FATAL_ERROR
      "Google Benchmark sources are missing. Run: git submodule update --init --recursive")
endif()

set(BENCHMARK_ENABLE_TESTING OFF CACHE BOOL "" FORCE)
set(BENCHMARK_ENABLE_GTEST_TESTS OFF CACHE BOOL "" FORCE)
set(BENCHMARK_ENABLE_INSTALL OFF CACHE BOOL "" FORCE)
set(BENCHMARK_ENABLE_WERROR OFF CACHE BOOL "" FORCE)
add_subdirectory(
  "${BENCHMARK_SOURCE_DIR}"
  "${CMAKE_CURRENT_BINARY_DIR}/third_party/benchmark"
  EXCLUDE_FROM_ALL)

if(NOT EXISTS "${MONAD_SOURCE_DIR}/CMakeLists.txt")
  message(
    FATAL_ERROR
      "Monad sources are missing. Run: git submodule update --init --recursive")
endif()

execute_process(
  COMMAND git -C "${MONAD_SOURCE_DIR}" rev-parse HEAD
  OUTPUT_VARIABLE MONAD_EXECBENCH_MONAD_COMMIT
  OUTPUT_STRIP_TRAILING_WHITESPACE
  COMMAND_ERROR_IS_FATAL ANY)

execute_process(
  COMMAND git -C "${CMAKE_CURRENT_SOURCE_DIR}" rev-parse HEAD
  OUTPUT_VARIABLE MONAD_EXECBENCH_COMMIT
  OUTPUT_STRIP_TRAILING_WHITESPACE
  COMMAND_ERROR_IS_FATAL ANY)
execute_process(
  COMMAND git -C "${CMAKE_CURRENT_SOURCE_DIR}" status --porcelain
          --untracked-files=no
  OUTPUT_VARIABLE MONAD_EXECBENCH_GIT_STATUS
  OUTPUT_STRIP_TRAILING_WHITESPACE
  COMMAND_ERROR_IS_FATAL ANY)
if(NOT MONAD_EXECBENCH_GIT_STATUS STREQUAL "")
  string(APPEND MONAD_EXECBENCH_COMMIT "-dirty")
endif()

# Monad stamps its binaries from GIT_COMMIT_HASH. Set it explicitly because
# Monad is configured as a subproject and CMAKE_SOURCE_DIR points at this repo.
set(ENV{GIT_COMMIT_HASH} "${MONAD_EXECBENCH_MONAD_COMMIT}")

set(MONAD_COMPILER_COVERAGE OFF CACHE BOOL "" FORCE)
set(MONAD_COMPILER_TESTING OFF CACHE BOOL "" FORCE)
set(MONAD_COMPILER_BENCHMARKS OFF CACHE BOOL "" FORCE)
set(MONAD_COMPILER_DUMP_ASM OFF CACHE BOOL "" FORCE)
set(MONAD_COMPILER_STATS OFF CACHE BOOL "" FORCE)
set(MONAD_COMPILER_HOT_PATH_STATS OFF CACHE BOOL "" FORCE)
set(MONAD_VM_INTERPRETER_DEBUG OFF CACHE BOOL "" FORCE)
set(MONAD_VM_INTERPRETER_STATS OFF CACHE BOOL "" FORCE)

option(MONAD_EXECBENCH_DIAGNOSTICS
       "Build the diagnostic runner instead of the timing runner" OFF)
if(DEFINED MONAD_EXECBENCH_BUILD_VARIANT AND
   NOT "${MONAD_EXECBENCH_BUILD_VARIANT}" STREQUAL "${MONAD_EXECBENCH_DIAGNOSTICS}")
  message(FATAL_ERROR "Timing and diagnostic builds require separate build directories")
endif()
set(MONAD_EXECBENCH_BUILD_VARIANT "${MONAD_EXECBENCH_DIAGNOSTICS}"
    CACHE INTERNAL "Build isolation")

add_subdirectory(
  "${MONAD_SOURCE_DIR}"
  "${CMAKE_CURRENT_BINARY_DIR}/third_party/monad"
  EXCLUDE_FROM_ALL)

if(MONAD_EXECBENCH_DIAGNOSTICS)
  string(TOUPPER "${CMAKE_BUILD_TYPE}" diagnostic_configuration)
  if(CMAKE_INTERPROCEDURAL_OPTIMIZATION OR
     CMAKE_INTERPROCEDURAL_OPTIMIZATION_${diagnostic_configuration})
    message(FATAL_ERROR "Diagnostic result-symbol wrapping does not support LTO")
  endif()
  if(NOT MONAD_EXECBENCH_MONAD_COMMIT STREQUAL "aae93c5352510f09640733e58159201d3cbad063")
    message(FATAL_ERROR "The diagnostic dispatch shim requires review for this Monad revision")
  endif()
  # Replace only the dispatch translation unit in this isolated build. All
  # instruction semantics, the VM, and the execution host remain upstream code.
  get_target_property(interpreter_sources monad-vm-interpreter SOURCES)
  list(FILTER interpreter_sources EXCLUDE REGEX "(^|/)execute\\.cpp$")
  set_property(TARGET monad-vm-interpreter
               PROPERTY SOURCES "${interpreter_sources}")
  target_sources(monad-vm-interpreter PRIVATE
                 "${CMAKE_CURRENT_SOURCE_DIR}/src/profiled_interpreter.cpp")
  target_include_directories(monad-vm-interpreter PRIVATE
                             "${CMAKE_CURRENT_SOURCE_DIR}/include")
  add_executable(monad-execbench
                 src/diagnostic_main.cpp src/diagnostic_result.cpp
                 src/diagnostics.cpp src/fixture.cpp src/hash.cpp src/replay.cpp)
  set_target_properties(monad-execbench
                        PROPERTIES OUTPUT_NAME monad-execbench-diagnostics)
  target_compile_definitions(monad-execbench PRIVATE MONAD_EXECBENCH_DIAGNOSTICS)
  set(result_symbol "_ZN5monad2vm7runtime7Context19copy_to_evmc_resultINS_11MonadTraitsIL14monad_revision10EEEEEN4evmc6ResultEv")
  target_compile_definitions(monad-execbench PRIVATE
                             MONAD_EXECBENCH_RESULT_SYMBOL="${result_symbol}")
  target_link_options(monad-execbench PRIVATE "LINKER:--wrap=${result_symbol}")
else()
  add_executable(monad-execbench
                 src/benchmark.cpp src/fixture.cpp src/hash.cpp src/main.cpp src/replay.cpp)
endif()

target_compile_features(monad-execbench PRIVATE cxx_std_23)
target_include_directories(monad-execbench PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_compile_options(
  monad-execbench
  PRIVATE -Wall -Wextra -Wconversion -Werror -Wno-missing-field-initializers)
target_compile_definitions(
  monad-execbench
  PRIVATE MONAD_EXECBENCH_VERSION="${PROJECT_VERSION}"
          MONAD_EXECBENCH_COMMIT="${MONAD_EXECBENCH_COMMIT}"
          MONAD_EXECBENCH_MONAD_COMMIT="${MONAD_EXECBENCH_MONAD_COMMIT}"
          MONAD_EXECBENCH_BUILD_TYPE="$<CONFIG>"
          MONAD_EXECBENCH_CXX_COMPILER_ID="${CMAKE_CXX_COMPILER_ID}"
          MONAD_EXECBENCH_CXX_COMPILER_VERSION="${CMAKE_CXX_COMPILER_VERSION}")
target_link_libraries(
  monad-execbench
  PRIVATE benchmark::benchmark
          evmc::mocked_host
          monad_crypto
          monad_execution)

include(CTest)

if(BUILD_TESTING AND NOT MONAD_EXECBENCH_DIAGNOSTICS)
  add_test(
    NAME monad-execbench-smoke
    COMMAND monad-execbench smoke --execution-env MONAD_TEN)
  add_test(
    NAME monad-execbench-verify-synthetic
    COMMAND monad-execbench verify
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/synthetic")
  add_test(
    NAME monad-execbench-reject-incomplete-state
    COMMAND
      "${CMAKE_COMMAND}"
      "-DPROGRAM=$<TARGET_FILE:monad-execbench>"
      "-DFIXTURE=${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/incomplete"
      "-DEXPECTED=uncaptured storage"
      -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/expect_failure.cmake")
  add_test(
    NAME monad-execbench-fixture-validation
    COMMAND
      "${CMAKE_COMMAND}"
      "-DPROGRAM=$<TARGET_FILE:monad-execbench>"
      "-DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}"
      "-DBINARY_DIR=${CMAKE_CURRENT_BINARY_DIR}"
      -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/fixture_validation.cmake")
  add_test(
    NAME monad-execbench-benchmark-dual-hot
    COMMAND
      "${CMAKE_COMMAND}"
      "-DPROGRAM=$<TARGET_FILE:monad-execbench>"
      "-DFIXTURE=${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/synthetic"
      "-DBINARY_DIR=${CMAKE_CURRENT_BINARY_DIR}"
      "-DMODE=dual-hot"
      "-DFILTER=return-constant"
      "-DEXPECTED_GAS=13"
      -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/benchmark_output.cmake")
  add_test(
    NAME monad-execbench-benchmark-interpreter-hot
    COMMAND
      "${CMAKE_COMMAND}"
      "-DPROGRAM=$<TARGET_FILE:monad-execbench>"
      "-DFIXTURE=${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/synthetic"
      "-DBINARY_DIR=${CMAKE_CURRENT_BINARY_DIR}"
      "-DMODE=interpreter-hot"
      "-DFILTER=nested-revert-rolls-back-state"
      "-DEXPECTED_GAS=38828"
      -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/benchmark_output.cmake")
  add_test(
    NAME monad-execbench-benchmark-cli
    COMMAND
      "${CMAKE_COMMAND}"
      "-DPROGRAM=$<TARGET_FILE:monad-execbench>"
      "-DFIXTURE=${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/synthetic"
      "-DBINARY_DIR=${CMAKE_CURRENT_BINARY_DIR}"
      -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/benchmark_cli.cmake")
endif()

install(TARGETS monad-execbench RUNTIME DESTINATION bin COMPONENT execbench)
