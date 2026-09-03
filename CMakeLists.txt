cmake_minimum_required(VERSION 3.27)

project(monad_execbench VERSION 0.1.0 LANGUAGES C CXX ASM)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(MONAD_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third_party/monad")

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

# Monad stamps its binaries from GIT_COMMIT_HASH. Set it explicitly because
# Monad is configured as a subproject and CMAKE_SOURCE_DIR points at this repo.
set(ENV{GIT_COMMIT_HASH} "${MONAD_EXECBENCH_MONAD_COMMIT}")

set(MONAD_COMPILER_COVERAGE OFF CACHE BOOL "" FORCE)
set(MONAD_COMPILER_TESTING OFF CACHE BOOL "" FORCE)
set(MONAD_COMPILER_BENCHMARKS OFF CACHE BOOL "" FORCE)
set(MONAD_COMPILER_DUMP_ASM OFF CACHE BOOL "" FORCE)
set(MONAD_COMPILER_STATS OFF CACHE BOOL "" FORCE)
set(MONAD_COMPILER_HOT_PATH_STATS OFF CACHE BOOL "" FORCE)

add_subdirectory(
  "${MONAD_SOURCE_DIR}"
  "${CMAKE_CURRENT_BINARY_DIR}/third_party/monad"
  EXCLUDE_FROM_ALL)

add_executable(monad-execbench src/fixture.cpp src/main.cpp src/replay.cpp)

target_compile_features(monad-execbench PRIVATE cxx_std_23)
target_include_directories(monad-execbench PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_compile_options(
  monad-execbench
  PRIVATE -Wall -Wextra -Wconversion -Werror -Wno-missing-field-initializers)
target_compile_definitions(
  monad-execbench
  PRIVATE MONAD_EXECBENCH_VERSION="${PROJECT_VERSION}"
          MONAD_EXECBENCH_MONAD_COMMIT="${MONAD_EXECBENCH_MONAD_COMMIT}")
target_link_libraries(
  monad-execbench
  PRIVATE evmc::mocked_host
          monad_execution)

include(CTest)

if(BUILD_TESTING)
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
endif()

install(TARGETS monad-execbench RUNTIME DESTINATION bin)
