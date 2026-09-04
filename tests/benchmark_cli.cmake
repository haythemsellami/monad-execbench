if(NOT DEFINED PROGRAM OR NOT DEFINED FIXTURE OR NOT DEFINED BINARY_DIR)
  message(FATAL_ERROR "PROGRAM, FIXTURE, and BINARY_DIR are required")
endif()

set(output "${BINARY_DIR}/benchmark-cli.json")

function(expect_failure expected)
  execute_process(
    COMMAND "${PROGRAM}" ${ARGN}
    RESULT_VARIABLE result
    OUTPUT_VARIABLE standard_output
    ERROR_VARIABLE standard_error)
  if(result EQUAL 0)
    message(FATAL_ERROR "command unexpectedly succeeded: ${ARGN}")
  endif()
  set(combined "${standard_output}${standard_error}")
  string(FIND "${combined}" "${expected}" position)
  if(position EQUAL -1)
    message(
      FATAL_ERROR
        "expected failure containing '${expected}', got:\n${combined}")
  endif()
endfunction()

expect_failure(
  "unsupported benchmark mode: cold"
  run "${FIXTURE}" --mode cold --output "${output}")
expect_failure(
  "--repetitions must be a positive integer"
  run "${FIXTURE}" --repetitions 0 --output "${output}")
expect_failure(
  "case filter matched no cases: absent-*"
  run "${FIXTURE}" --filter "absent-*" --output "${output}")
expect_failure(
  "run requires --output <path>"
  run "${FIXTURE}")
expect_failure(
  "Google Benchmark option is controlled by monad-execbench"
  run "${FIXTURE}" --output "${output}" -- --benchmark_repetitions=3)

execute_process(
  COMMAND "${PROGRAM}" run --help
  RESULT_VARIABLE help_result
  OUTPUT_VARIABLE help_output
  ERROR_VARIABLE help_error)
if(NOT help_result EQUAL 0)
  message(FATAL_ERROR "run --help failed\n${help_output}\n${help_error}")
endif()
string(FIND "${help_output}" "--mode dual-hot|interpreter-hot" help_mode)
if(help_mode EQUAL -1)
  message(FATAL_ERROR "run --help omitted benchmark modes")
endif()

file(REMOVE "${output}")
