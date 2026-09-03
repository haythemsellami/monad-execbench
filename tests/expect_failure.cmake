if(NOT DEFINED PROGRAM OR NOT DEFINED FIXTURE OR NOT DEFINED EXPECTED)
  message(FATAL_ERROR "PROGRAM, FIXTURE, and EXPECTED are required")
endif()

execute_process(
  COMMAND "${PROGRAM}" verify "${FIXTURE}"
  RESULT_VARIABLE result
  OUTPUT_VARIABLE standard_output
  ERROR_VARIABLE standard_error)

if(result EQUAL 0)
  message(FATAL_ERROR "command unexpectedly succeeded\n${standard_output}")
endif()

set(combined_output "${standard_output}${standard_error}")
string(FIND "${combined_output}" "${EXPECTED}" expected_position)
if(expected_position EQUAL -1)
  message(
    FATAL_ERROR
      "command failed without expected output '${EXPECTED}'\n${combined_output}")
endif()

message(STATUS "observed expected failure: ${EXPECTED}")
