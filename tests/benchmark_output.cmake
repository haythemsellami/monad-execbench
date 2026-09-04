if(NOT DEFINED PROGRAM OR NOT DEFINED FIXTURE OR NOT DEFINED BINARY_DIR OR
   NOT DEFINED MODE OR NOT DEFINED FILTER OR NOT DEFINED EXPECTED_GAS)
  message(
    FATAL_ERROR
      "PROGRAM, FIXTURE, BINARY_DIR, MODE, FILTER, and EXPECTED_GAS are required")
endif()

set(output_directory "${BINARY_DIR}/benchmark-output-${MODE}")
set(output "${output_directory}/${MODE}.json")
file(REMOVE_RECURSE "${output_directory}")
file(MAKE_DIRECTORY "${output_directory}")

execute_process(
  COMMAND
    "${PROGRAM}" run "${FIXTURE}" --mode "${MODE}" --repetitions 2
    --filter "${FILTER}" --output "${output}" --
    --benchmark_min_time=0.001s
  RESULT_VARIABLE result
  OUTPUT_VARIABLE standard_output
  ERROR_VARIABLE standard_error)

if(NOT result EQUAL 0)
  message(
    FATAL_ERROR
      "benchmark command failed\n${standard_output}\n${standard_error}")
endif()
if(NOT EXISTS "${output}")
  message(FATAL_ERROR "benchmark command did not create ${output}")
endif()

file(READ "${output}" report)
string(JSON report_mode GET "${report}" context benchmark_mode)
if(NOT report_mode STREQUAL "${MODE}")
  message(FATAL_ERROR "expected mode ${MODE}, got ${report_mode}")
endif()
string(JSON execution_env GET "${report}" context execution_env)
if(NOT execution_env STREQUAL "MONAD_TEN")
  message(FATAL_ERROR "expected MONAD_TEN, got ${execution_env}")
endif()
string(JSON monad_commit GET "${report}" context monad_commit)
if(monad_commit STREQUAL "")
  message(FATAL_ERROR "benchmark report omitted the Monad commit")
endif()
string(JSON runner_commit GET "${report}" context monad_execbench_commit)
if(runner_commit STREQUAL "")
  message(FATAL_ERROR "benchmark report omitted the runner commit")
endif()

string(JSON benchmark_count LENGTH "${report}" benchmarks)
set(raw_repetitions 0)
math(EXPR last_benchmark "${benchmark_count} - 1")
foreach(index RANGE 0 ${last_benchmark})
  string(JSON run_type GET "${report}" benchmarks ${index} run_type)
  if(run_type STREQUAL "iteration")
    math(EXPR raw_repetitions "${raw_repetitions} + 1")
    string(JSON name GET "${report}" benchmarks ${index} name)
    string(FIND "${name}" "execute/${MODE}/${FILTER}" expected_name)
    if(expected_name EQUAL -1)
      message(FATAL_ERROR "unexpected benchmark name: ${name}")
    endif()
    string(JSON gas GET "${report}" benchmarks ${index} execution_gas)
    if(NOT gas EQUAL "${EXPECTED_GAS}")
      message(FATAL_ERROR "expected gas ${EXPECTED_GAS}, got ${gas}")
    endif()
    if(FILTER STREQUAL "return-constant")
      string(JSON amount_in GET "${report}" benchmarks ${index} amount_in)
      if(NOT amount_in EQUAL 10000000)
        message(FATAL_ERROR "unexpected amount_in counter: ${amount_in}")
      endif()
      string(JSON label_json GET "${report}" benchmarks ${index} label)
      string(JSON status GET "${label_json}" status)
      string(JSON implementation GET "${label_json}" labels implementation)
      string(JSON exact_amount GET "${label_json}" counters amount_in)
      if(NOT status STREQUAL "success" OR
         NOT implementation STREQUAL "synthetic" OR
         NOT exact_amount STREQUAL "10000000")
        message(FATAL_ERROR "unexpected metadata label: ${label_json}")
      endif()
    endif()
  endif()
endforeach()

if(NOT raw_repetitions EQUAL 2)
  message(FATAL_ERROR "expected 2 raw repetitions, got ${raw_repetitions}")
endif()

string(FIND "${standard_output}" "verification=passed" verified)
if(verified EQUAL -1)
  message(FATAL_ERROR "benchmark command did not report verification")
endif()
string(FIND "${standard_output}" "results=${output}" reported_output)
if(reported_output EQUAL -1)
  message(FATAL_ERROR "benchmark command did not report its output path")
endif()

file(REMOVE_RECURSE "${output_directory}")
