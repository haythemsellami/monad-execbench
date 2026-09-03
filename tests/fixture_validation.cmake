if(NOT DEFINED PROGRAM OR NOT DEFINED SOURCE_DIR OR NOT DEFINED BINARY_DIR)
  message(FATAL_ERROR "PROGRAM, SOURCE_DIR, and BINARY_DIR are required")
endif()

set(fixture_dir "${BINARY_DIR}/fixture-validation")
set(source_fixture "${SOURCE_DIR}/tests/fixtures/synthetic")

file(REMOVE_RECURSE "${fixture_dir}")
file(MAKE_DIRECTORY "${fixture_dir}")
file(COPY "${source_fixture}/" DESTINATION "${fixture_dir}")
file(READ "${fixture_dir}/manifest.json" manifest)
file(READ "${fixture_dir}/cases.json" cases)

function(expect_fixture_failure expected)
  execute_process(
    COMMAND "${PROGRAM}" verify "${fixture_dir}"
    RESULT_VARIABLE result
    OUTPUT_VARIABLE stdout
    ERROR_VARIABLE stderr)
  if(result EQUAL 0)
    message(FATAL_ERROR "fixture unexpectedly passed validation")
  endif()

  set(output "${stdout}${stderr}")
  string(FIND "${output}" "${expected}" position)
  if(position EQUAL -1)
    message(
      FATAL_ERROR
        "expected failure containing '${expected}', got:\n${output}")
  endif()
endfunction()

string(JSON missing_chain_id REMOVE "${manifest}" chain chainId)
file(WRITE "${fixture_dir}/manifest.json" "${missing_chain_id}")
expect_fixture_failure(
  "invalid fixture at manifest.chain.chainId: missing required field")

file(WRITE "${fixture_dir}/manifest.json" "${manifest}")
string(
  REPLACE "\"accessList\": []"
          "\"accessList\": [{\"storageKeys\": []}]"
          missing_access_list_address
          "${cases}")
file(WRITE "${fixture_dir}/cases.json" "${missing_access_list_address}")
expect_fixture_failure(
  "invalid fixture at cases[0].message.accessList[0].address: missing required field")

file(WRITE "${fixture_dir}/cases.json" "${cases}")
string(
  REPLACE "\"logs\": []"
          "\"logs\": [{\"address\": \"0x2000000000000000000000000000000000000001\", \"topics\": []}]"
          missing_log_data
          "${cases}")
file(WRITE "${fixture_dir}/cases.json" "${missing_log_data}")
expect_fixture_failure(
  "invalid fixture at cases[0].expected.logs[0].data: missing required field")

file(WRITE "${fixture_dir}/cases.json" "${cases}")
string(
  JSON excessive_message_gas
  SET "${cases}" 0 message gas "\"9223372036854775808\"")
file(WRITE "${fixture_dir}/cases.json" "${excessive_message_gas}")
expect_fixture_failure(
  "invalid fixture at cases[0].message.gas: exceeds the EVMC signed gas range")

file(WRITE "${fixture_dir}/cases.json" "${cases}")
find_program(truncate_executable truncate REQUIRED)
execute_process(
  COMMAND "${truncate_executable}" -s 536870913 "${fixture_dir}/oversized.json"
  COMMAND_ERROR_IS_FATAL ANY)
string(
  REPLACE "\"state\": \"state.json\""
          "\"state\": \"oversized.json\""
          oversized_manifest
          "${manifest}")
file(WRITE "${fixture_dir}/manifest.json" "${oversized_manifest}")
expect_fixture_failure("fixture file exceeds 512 MiB")

file(REMOVE_RECURSE "${fixture_dir}")
