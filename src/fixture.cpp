#include <monad-execbench/fixture.hpp>
#include <monad-execbench/hash.hpp>

#include <category/core/hex.hpp>
#include <category/core/keccak.hpp>

#include <nlohmann/json.hpp>
#include <zstd.h>

#include <algorithm>
#include <charconv>
#include <cmath>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <system_error>
#include <utility>

namespace monad_execbench
{
    namespace
    {
        using json = nlohmann::json;
        constexpr std::uintmax_t max_fixture_file_size =
            512ULL * 1024ULL * 1024ULL;

        [[noreturn]] void
        invalid(std::string const &path, std::string const &message)
        {
            throw std::runtime_error{
                "invalid fixture at " + path + ": " + message};
        }

        json read_json(
            std::filesystem::path const &path,
            std::string *encoded_payload = nullptr,
            std::string *decoded_payload = nullptr)
        {
            std::error_code file_size_error;
            auto const file_size =
                std::filesystem::file_size(path, file_size_error);
            if (file_size_error) {
                throw std::runtime_error{
                    "cannot inspect fixture file " + path.string() + ": " +
                    file_size_error.message()};
            }
            if (file_size > max_fixture_file_size) {
                throw std::runtime_error{
                    "fixture file exceeds 512 MiB: " + path.string()};
            }

            std::ifstream input{path, std::ios::binary};
            if (!input) {
                throw std::runtime_error{
                    "cannot open fixture file: " + path.string()};
            }

            std::string payload(static_cast<std::size_t>(file_size), '\0');
            if (file_size != 0) {
                input.read(
                    payload.data(), static_cast<std::streamsize>(file_size));
            }
            if (input.gcount() != static_cast<std::streamsize>(file_size) ||
                input.peek() != std::ifstream::traits_type::eof()) {
                throw std::runtime_error{
                    "fixture file changed while reading: " + path.string()};
            }
            if (encoded_payload != nullptr) {
                *encoded_payload = payload;
            }
            if (path.extension() == ".zst") {
                auto const size =
                    ZSTD_getFrameContentSize(payload.data(), payload.size());
                if (size == ZSTD_CONTENTSIZE_ERROR) {
                    throw std::runtime_error{
                        "invalid zstd fixture file: " + path.string()};
                }
                if (size == ZSTD_CONTENTSIZE_UNKNOWN) {
                    throw std::runtime_error{
                        "zstd fixture must declare its decompressed size: " +
                        path.string()};
                }
                if (size > max_fixture_file_size) {
                    throw std::runtime_error{
                        "decompressed fixture file exceeds 512 MiB: " +
                        path.string()};
                }

                std::string decompressed(static_cast<std::size_t>(size), '\0');
                auto const result = ZSTD_decompress(
                    decompressed.data(),
                    decompressed.size(),
                    payload.data(),
                    payload.size());
                if (ZSTD_isError(result) != 0 ||
                    result != decompressed.size()) {
                    throw std::runtime_error{
                        "cannot decompress fixture file " + path.string() +
                        ": " + ZSTD_getErrorName(result)};
                }
                payload = std::move(decompressed);
            }
            if (decoded_payload != nullptr) {
                *decoded_payload = payload;
            }

            try {
                return json::parse(payload);
            }
            catch (json::parse_error const &error) {
                throw std::runtime_error{
                    "cannot parse fixture file " + path.string() + ": " +
                    error.what()};
            }
        }

        json const *
        required_field(json const &object, char const *key, std::string path)
        {
            if (!object.is_object()) {
                invalid(path, "expected an object");
            }
            auto const field = object.find(key);
            if (field == object.end()) {
                invalid(path + "." + key, "missing required field");
            }
            return &*field;
        }

        std::string required_string(
            json const &object, char const *key, std::string const &path)
        {
            auto const &value = *required_field(object, key, path);
            if (!value.is_string()) {
                invalid(path + "." + key, "expected a string");
            }
            return value.get<std::string>();
        }

        template <typename T>
        T fixed_hex(json const &value, std::string const &path)
        {
            if (!value.is_string()) {
                invalid(path, "expected a 0x-prefixed hexadecimal string");
            }
            auto const text = value.get<std::string>();
            if (!text.starts_with("0x") || text.size() != 2 + sizeof(T) * 2) {
                invalid(
                    path,
                    "expected exactly " + std::to_string(sizeof(T)) + " bytes");
            }
            auto parsed = monad::from_hex<T>(text);
            if (!parsed.has_value()) {
                invalid(path, "invalid hexadecimal value");
            }
            return parsed.value();
        }

        monad::byte_string bytes(json const &value, std::string const &path)
        {
            if (!value.is_string()) {
                invalid(path, "expected a 0x-prefixed hexadecimal string");
            }
            auto const text = value.get<std::string>();
            if (!text.starts_with("0x") || text.size() % 2 != 0) {
                invalid(
                    path,
                    "expected an even-length 0x-prefixed hexadecimal string");
            }
            auto parsed = monad::from_hex(text);
            if (!parsed.has_value()) {
                invalid(path, "invalid hexadecimal value");
            }
            return parsed.value();
        }

        monad::uint256_t uint256(json const &value, std::string const &path)
        {
            if (value.is_number_unsigned()) {
                return monad::uint256_t{value.get<std::uint64_t>()};
            }
            if (!value.is_string()) {
                invalid(
                    path,
                    "expected an unsigned integer or decimal/0x-prefixed "
                    "integer string");
            }
            try {
                return monad::from_string<monad::uint256_t>(
                    value.get<std::string>());
            }
            catch (std::exception const &error) {
                invalid(path, error.what());
            }
        }

        std::uint64_t uint64(json const &value, std::string const &path)
        {
            if (value.is_number_unsigned()) {
                return value.get<std::uint64_t>();
            }
            if (!value.is_string()) {
                invalid(path, "expected an unsigned integer or integer string");
            }

            auto text = value.get<std::string>();
            int base = 10;
            if (text.starts_with("0x")) {
                text.erase(0, 2);
                base = 16;
            }
            if (text.empty()) {
                invalid(path, "empty integer");
            }
            std::uint64_t result{};
            auto const parsed = std::from_chars(
                text.data(), text.data() + text.size(), result, base);
            if (parsed.ec != std::errc{} ||
                parsed.ptr != text.data() + text.size()) {
                invalid(path, "integer is invalid or out of range");
            }
            return result;
        }

        std::uint64_t message_gas(json const &value, std::string const &path)
        {
            auto const result = uint64(value, path);
            if (result > static_cast<std::uint64_t>(
                             std::numeric_limits<std::int64_t>::max())) {
                invalid(path, "exceeds the EVMC signed gas range");
            }
            return result;
        }

        std::filesystem::path referenced_file(
            std::filesystem::path const &directory, json const &manifest,
            char const *key, char const *default_name)
        {
            auto relative = std::filesystem::path{
                manifest.contains(key)
                    ? required_string(manifest, key, "manifest")
                    : std::string{default_name}};
            if (relative.empty() || relative.is_absolute()) {
                invalid(
                    std::string{"manifest."} + key, "must be a relative path");
            }
            auto const normalized = relative.lexically_normal();
            if (*normalized.begin() == "..") {
                invalid(
                    std::string{"manifest."} + key,
                    "must stay inside the suite directory");
            }
            return directory / normalized;
        }

        std::vector<StorageSlot>
        storage(json const &value, std::string const &path)
        {
            if (!value.is_object()) {
                invalid(path, "expected an object");
            }
            std::vector<StorageSlot> result;
            result.reserve(value.size());
            for (auto const &[key, slot_value] : value.items()) {
                json const key_json = key;
                result.push_back(StorageSlot{
                    .key =
                        fixed_hex<monad::bytes32_t>(key_json, path + "." + key),
                    .value = fixed_hex<monad::bytes32_t>(
                        slot_value, path + "." + key)});
            }
            return result;
        }

        monad::AccessList
        access_list(json const &value, std::string const &path)
        {
            if (!value.is_array()) {
                invalid(path, "expected an array");
            }
            monad::AccessList result;
            result.reserve(value.size());
            for (std::size_t i = 0; i < value.size(); ++i) {
                auto const &entry = value.at(i);
                auto const entry_path = path + "[" + std::to_string(i) + "]";
                auto const &address =
                    *required_field(entry, "address", entry_path);
                auto const &storage_keys =
                    *required_field(entry, "storageKeys", entry_path);
                if (!storage_keys.is_array()) {
                    invalid(entry_path + ".storageKeys", "expected an array");
                }
                monad::AccessEntry parsed{
                    .a = fixed_hex<monad::Address>(
                        address, entry_path + ".address")};
                for (std::size_t j = 0; j < storage_keys.size(); ++j) {
                    parsed.keys.push_back(fixed_hex<monad::bytes32_t>(
                        storage_keys.at(j),
                        entry_path + ".storageKeys[" + std::to_string(j) +
                            "]"));
                }
                result.push_back(std::move(parsed));
            }
            return result;
        }

        std::vector<monad::Receipt::Log>
        logs(json const &value, std::string const &path)
        {
            if (!value.is_array()) {
                invalid(path, "expected an array");
            }
            std::vector<monad::Receipt::Log> result;
            result.reserve(value.size());
            for (std::size_t i = 0; i < value.size(); ++i) {
                auto const &entry = value.at(i);
                auto const entry_path = path + "[" + std::to_string(i) + "]";
                auto const &address =
                    *required_field(entry, "address", entry_path);
                auto const &data = *required_field(entry, "data", entry_path);
                auto const &topics =
                    *required_field(entry, "topics", entry_path);
                if (!topics.is_array()) {
                    invalid(entry_path + ".topics", "expected an array");
                }
                monad::Receipt::Log log{
                    .data = bytes(data, entry_path + ".data"),
                    .topics = {},
                    .address = fixed_hex<monad::Address>(
                        address, entry_path + ".address")};
                for (std::size_t j = 0; j < topics.size(); ++j) {
                    log.topics.push_back(fixed_hex<monad::bytes32_t>(
                        topics.at(j),
                        entry_path + ".topics[" + std::to_string(j) + "]"));
                }
                result.push_back(std::move(log));
            }
            return result;
        }

        std::vector<ExpectedAccount>
        expected_state(json const &value, std::string const &path)
        {
            if (!value.is_object()) {
                invalid(path, "expected an object");
            }
            std::vector<ExpectedAccount> result;
            result.reserve(value.size());
            for (auto const &[address_text, account] : value.items()) {
                auto const account_path = path + "." + address_text;
                if (!account.is_object()) {
                    invalid(account_path, "expected an object");
                }
                json const address_json = address_text;
                ExpectedAccount parsed{
                    .address =
                        fixed_hex<monad::Address>(address_json, account_path)};
                if (account.contains("balance")) {
                    parsed.balance = uint256(
                        account.at("balance"), account_path + ".balance");
                }
                if (account.contains("nonce")) {
                    parsed.nonce =
                        uint64(account.at("nonce"), account_path + ".nonce");
                }
                if (account.contains("code")) {
                    parsed.code =
                        bytes(account.at("code"), account_path + ".code");
                }
                if (account.contains("storage")) {
                    parsed.storage = storage(
                        account.at("storage"), account_path + ".storage");
                }
                if (!parsed.balance && !parsed.nonce && !parsed.code &&
                    parsed.storage.empty()) {
                    invalid(
                        account_path, "expected at least one state assertion");
                }
                result.push_back(std::move(parsed));
            }
            return result;
        }

        bool valid_metadata_key(std::string const &key)
        {
            if (key.empty() || key.size() > 64) {
                return false;
            }
            auto const name_start = [](unsigned char character) {
                return character == '_' ||
                       (character >= 'a' && character <= 'z') ||
                       (character >= 'A' && character <= 'Z');
            };
            if (!name_start(static_cast<unsigned char>(key.front()))) {
                return false;
            }
            return std::all_of(
                key.begin() + 1,
                key.end(),
                [&name_start](unsigned char character) {
                    return name_start(character) ||
                           (character >= '0' && character <= '9') ||
                           character == '.' || character == '-';
                });
        }

        void
        validate_metadata_key(std::string const &key, std::string const &path)
        {
            if (!valid_metadata_key(key)) {
                invalid(path, "must match [A-Za-z_][A-Za-z0-9_.-]{0,63}");
            }
        }

        CaseMetadata metadata(json const &value, std::string const &path)
        {
            if (!value.is_object()) {
                invalid(path, "expected an object");
            }
            CaseMetadata result;
            if (value.contains("labels")) {
                auto const &labels = value.at("labels");
                if (!labels.is_object() || labels.empty()) {
                    invalid(path + ".labels", "expected a non-empty object");
                }
                for (auto const &[key, label] : labels.items()) {
                    validate_metadata_key(key, path + ".labels key");
                    if (!label.is_string()) {
                        invalid(path + ".labels." + key, "expected a string");
                    }
                    result.labels.emplace_back(key, label.get<std::string>());
                }
            }
            if (value.contains("counters")) {
                auto const &counters = value.at("counters");
                if (!counters.is_object() || counters.empty()) {
                    invalid(path + ".counters", "expected a non-empty object");
                }
                for (auto const &[key, counter] : counters.items()) {
                    validate_metadata_key(key, path + ".counters key");
                    if (key == "execution_gas" || key == "return_data_bytes" ||
                        key == "log_count") {
                        invalid(
                            path + ".counters." + key,
                            "counter name is reserved");
                    }
                    std::string exact_value;
                    if (counter.is_number_unsigned()) {
                        exact_value =
                            std::to_string(counter.get<std::uint64_t>());
                    }
                    else if (counter.is_string()) {
                        exact_value = counter.get<std::string>();
                        if (exact_value.empty() ||
                            !std::all_of(
                                exact_value.begin(),
                                exact_value.end(),
                                [](unsigned char character) {
                                    return character >= '0' && character <= '9';
                                })) {
                            invalid(
                                path + ".counters." + key,
                                "expected a decimal unsigned integer");
                        }
                    }
                    else {
                        invalid(
                            path + ".counters." + key,
                            "expected an unsigned integer or decimal string");
                    }
                    (void)uint256(counter, path + ".counters." + key);
                    double benchmark_value{};
                    try {
                        benchmark_value = std::stod(exact_value);
                    }
                    catch (std::exception const &) {
                        invalid(
                            path + ".counters." + key,
                            "cannot represent counter for benchmarking");
                    }
                    if (!std::isfinite(benchmark_value)) {
                        invalid(
                            path + ".counters." + key,
                            "cannot represent counter for benchmarking");
                    }
                    result.counters.push_back(CaseCounter{
                        .name = key,
                        .exact_value = std::move(exact_value),
                        .benchmark_value = benchmark_value});
                }
            }
            if (result.labels.empty() && result.counters.empty()) {
                invalid(path, "expected at least one label or counter");
            }
            for (auto const &[key, ignored] : value.items()) {
                (void)ignored;
                if (key != "labels" && key != "counters") {
                    invalid(path + "." + key, "unknown field");
                }
            }
            return result;
        }

        std::string required_sha256(
            json const &object, char const *key, std::string const &path)
        {
            auto const result = required_string(object, key, path);
            if (result.size() != 66 || !result.starts_with("0x") ||
                !std::all_of(
                    result.begin() + 2,
                    result.end(),
                    [](unsigned char character) {
                        return (character >= '0' && character <= '9') ||
                               (character >= 'a' && character <= 'f');
                    })) {
                invalid(
                    path + "." + key,
                    "expected a lowercase 0x-prefixed SHA-256 digest");
            }
            return result;
        }

        void require_matching_hash(
            json const &object, char const *key, std::string const &actual,
            std::string const &path)
        {
            auto const declared = required_sha256(object, key, path);
            if (declared != actual) {
                invalid(path + "." + key, "does not match fixture content");
            }
        }

        FixtureProvenance validate_provenance(
            json const &value, FixtureSuite const &suite,
            std::string const &manifest_payload,
            std::string const &cases_payload,
            std::string const &state_file_payload,
            std::string const &state_payload, std::string const &cases_name,
            std::string const &state_name)
        {
            if (!value.is_object()) {
                invalid("provenance", "expected an object");
            }
            FixtureProvenance result{
                .schema = required_string(value, "schema", "provenance"),
                .created_at = required_string(value, "createdAt", "provenance"),
                .monad_commit =
                    required_string(value, "monadCommit", "provenance")};
            if (result.schema != provenance_schema_v1) {
                invalid(
                    "provenance.schema", "unsupported schema " + result.schema);
            }
            if (result.created_at.empty()) {
                invalid("provenance.createdAt", "must not be empty");
            }
            if (result.monad_commit != MONAD_EXECBENCH_MONAD_COMMIT) {
                invalid(
                    "provenance.monadCommit",
                    "does not match runner Monad commit " +
                        std::string{MONAD_EXECBENCH_MONAD_COMMIT});
            }

            auto const &source = *required_field(value, "source", "provenance");
            if (uint256(
                    *required_field(source, "chainId", "provenance.source"),
                    "provenance.source.chainId") != suite.chain_id) {
                invalid(
                    "provenance.source.chainId",
                    "does not match manifest chain ID");
            }
            if (uint64(
                    *required_field(source, "blockNumber", "provenance.source"),
                    "provenance.source.blockNumber") != suite.block.number) {
                invalid(
                    "provenance.source.blockNumber",
                    "does not match manifest block number");
            }
            if (fixed_hex<monad::bytes32_t>(
                    *required_field(source, "blockHash", "provenance.source"),
                    "provenance.source.blockHash") != suite.block.hash) {
                invalid(
                    "provenance.source.blockHash",
                    "does not match manifest block hash");
            }
            if (required_string(value, "executionEnv", "provenance") !=
                suite.execution_env) {
                invalid(
                    "provenance.executionEnv",
                    "does not match manifest execution environment");
            }

            auto const &capture_tool =
                *required_field(value, "captureTool", "provenance");
            result.capture_tool =
                required_string(capture_tool, "name", "provenance.captureTool");
            result.capture_version = required_string(
                capture_tool, "version", "provenance.captureTool");
            if (result.capture_tool.empty() || result.capture_version.empty()) {
                invalid(
                    "provenance.captureTool",
                    "name and version must not be empty");
            }

            result.manifest_sha256 = sha256_hex(manifest_payload);
            result.cases_sha256 = sha256_hex(cases_payload);
            result.state_file_sha256 = sha256_hex(state_file_payload);
            result.normalized_state_sha256 = sha256_hex(state_payload);
            result.bundle_sha256 = sha256_hex(
                result.manifest_sha256 + result.cases_sha256 +
                result.normalized_state_sha256);

            auto const &files = *required_field(value, "files", "provenance");
            require_matching_hash(
                files,
                "manifest.json",
                result.manifest_sha256,
                "provenance.files");
            require_matching_hash(
                files,
                cases_name.c_str(),
                result.cases_sha256,
                "provenance.files");
            require_matching_hash(
                files,
                state_name.c_str(),
                result.state_file_sha256,
                "provenance.files");

            auto const &normalized =
                *required_field(value, "normalized", "provenance");
            require_matching_hash(
                normalized,
                "manifestSha256",
                result.manifest_sha256,
                "provenance.normalized");
            require_matching_hash(
                normalized,
                "casesSha256",
                result.cases_sha256,
                "provenance.normalized");
            require_matching_hash(
                normalized,
                "stateSha256",
                result.normalized_state_sha256,
                "provenance.normalized");
            require_matching_hash(
                normalized,
                "bundleSha256",
                result.bundle_sha256,
                "provenance.normalized");
            return result;
        }
    }

    FixtureSuite load_fixture_suite(std::filesystem::path const &directory)
    {
        auto const normalized_directory =
            std::filesystem::absolute(directory).lexically_normal();
        if (!std::filesystem::is_directory(normalized_directory)) {
            throw std::runtime_error{
                "fixture suite is not a directory: " +
                normalized_directory.string()};
        }

        std::string manifest_payload;
        auto const manifest = read_json(
            normalized_directory / "manifest.json", &manifest_payload);
        FixtureSuite suite{
            .directory = normalized_directory,
            .schema = required_string(manifest, "schema", "manifest")};
        if (suite.schema != schema_v1) {
            invalid("manifest.schema", "unsupported schema " + suite.schema);
        }

        auto const &chain = *required_field(manifest, "chain", "manifest");
        if (!chain.is_object()) {
            invalid("manifest.chain", "expected an object");
        }
        suite.chain_id = uint256(
            *required_field(chain, "chainId", "manifest.chain"),
            "manifest.chain.chainId");
        suite.execution_env =
            required_string(chain, "executionEnv", "manifest.chain");

        auto const &block = *required_field(manifest, "block", "manifest");
        if (!block.is_object()) {
            invalid("manifest.block", "expected an object");
        }
        suite.block.number = uint64(
            *required_field(block, "number", "manifest.block"),
            "manifest.block.number");
        suite.block.hash = fixed_hex<monad::bytes32_t>(
            *required_field(block, "hash", "manifest.block"),
            "manifest.block.hash");
        suite.block.parent_hash = fixed_hex<monad::bytes32_t>(
            *required_field(block, "parentHash", "manifest.block"),
            "manifest.block.parentHash");
        suite.block.timestamp = uint64(
            *required_field(block, "timestamp", "manifest.block"),
            "manifest.block.timestamp");
        suite.block.gas_limit = uint64(
            *required_field(block, "gasLimit", "manifest.block"),
            "manifest.block.gasLimit");
        suite.block.base_fee = uint256(
            *required_field(block, "baseFee", "manifest.block"),
            "manifest.block.baseFee");
        suite.block.beneficiary = fixed_hex<monad::Address>(
            *required_field(block, "beneficiary", "manifest.block"),
            "manifest.block.beneficiary");
        suite.block.prev_randao = fixed_hex<monad::bytes32_t>(
            *required_field(block, "prevRandao", "manifest.block"),
            "manifest.block.prevRandao");
        if (suite.block.number > 0) {
            suite.block.block_hashes.emplace_back(
                suite.block.number - 1, suite.block.parent_hash);
        }
        if (block.contains("blockHashes")) {
            if (!block.at("blockHashes").is_object()) {
                invalid("manifest.block.blockHashes", "expected an object");
            }
            for (auto const &[number, hash] : block.at("blockHashes").items()) {
                json const number_json = number;
                auto const parsed_number =
                    uint64(number_json, "manifest.block.blockHashes." + number);
                auto const parsed_hash = fixed_hex<monad::bytes32_t>(
                    hash, "manifest.block.blockHashes." + number);
                auto existing = std::find_if(
                    suite.block.block_hashes.begin(),
                    suite.block.block_hashes.end(),
                    [parsed_number](auto const &entry) {
                        return entry.first == parsed_number;
                    });
                if (existing == suite.block.block_hashes.end()) {
                    suite.block.block_hashes.emplace_back(
                        parsed_number, parsed_hash);
                }
                else if (existing->second != parsed_hash) {
                    invalid(
                        "manifest.block.blockHashes." + number,
                        "conflicts with parentHash");
                }
            }
        }

        auto const state_path = referenced_file(
            normalized_directory, manifest, "state", "state.json.zst");
        auto const state_name =
            state_path.lexically_relative(normalized_directory)
                .generic_string();
        std::string state_file_payload;
        std::string state_payload;
        auto const state_json =
            read_json(state_path, &state_file_payload, &state_payload);
        auto const &accounts = *required_field(state_json, "accounts", "state");
        if (!accounts.is_object()) {
            invalid("state.accounts", "expected an object");
        }
        for (auto const &[address_text, account] : accounts.items()) {
            auto const account_path = "state.accounts." + address_text;
            if (!account.is_object()) {
                invalid(account_path, "expected an object");
            }
            json const address_json = address_text;
            AccountFixture parsed{
                .address =
                    fixed_hex<monad::Address>(address_json, account_path),
                .balance = uint256(
                    *required_field(account, "balance", account_path),
                    account_path + ".balance"),
                .nonce = uint64(
                    *required_field(account, "nonce", account_path),
                    account_path + ".nonce"),
                .code = bytes(
                    *required_field(account, "code", account_path),
                    account_path + ".code"),
                .code_hash = {},
                .storage = storage(
                    *required_field(account, "storage", account_path),
                    account_path + ".storage")};
            parsed.code_hash = monad::to_bytes(monad::keccak256(parsed.code));
            auto const declared = fixed_hex<monad::bytes32_t>(
                *required_field(account, "codeHash", account_path),
                account_path + ".codeHash");
            if (declared != parsed.code_hash) {
                invalid(
                    account_path + ".codeHash", "does not match runtime code");
            }
            suite.accounts.push_back(std::move(parsed));
        }

        if (state_json.contains("absentAccounts")) {
            if (!state_json.at("absentAccounts").is_array()) {
                invalid("state.absentAccounts", "expected an array");
            }
            for (std::size_t i = 0; i < state_json.at("absentAccounts").size();
                 ++i) {
                auto const address = fixed_hex<monad::Address>(
                    state_json.at("absentAccounts").at(i),
                    "state.absentAccounts[" + std::to_string(i) + "]");
                auto const present = std::find_if(
                    suite.accounts.begin(),
                    suite.accounts.end(),
                    [&address](auto const &account) {
                        return account.address == address;
                    });
                if (present != suite.accounts.end()) {
                    invalid(
                        "state.absentAccounts[" + std::to_string(i) + "]",
                        "account is also present in state.accounts");
                }
                suite.absent_accounts.push_back(address);
            }
        }

        auto const cases_path = referenced_file(
            normalized_directory, manifest, "cases", "cases.json");
        auto const cases_name =
            cases_path.lexically_relative(normalized_directory)
                .generic_string();
        std::string cases_payload;
        auto const cases_json = read_json(cases_path, &cases_payload);
        if (!cases_json.is_array() || cases_json.empty()) {
            invalid("cases", "expected a non-empty array");
        }
        for (std::size_t i = 0; i < cases_json.size(); ++i) {
            auto const &value = cases_json.at(i);
            auto const path = "cases[" + std::to_string(i) + "]";
            auto const &message = *required_field(value, "message", path);
            if (!message.is_object()) {
                invalid(path + ".message", "expected an object");
            }
            auto const &expected = *required_field(value, "expected", path);
            if (!expected.is_object()) {
                invalid(path + ".expected", "expected an object");
            }
            ReplayCase parsed{
                .name = required_string(value, "name", path),
                .message =
                    MessageFixture{
                        .sender = fixed_hex<monad::Address>(
                            *required_field(message, "from", path + ".message"),
                            path + ".message.from"),
                        .recipient = fixed_hex<monad::Address>(
                            *required_field(message, "to", path + ".message"),
                            path + ".message.to"),
                        .input = bytes(
                            *required_field(
                                message, "input", path + ".message"),
                            path + ".message.input"),
                        .value = uint256(
                            *required_field(
                                message, "value", path + ".message"),
                            path + ".message.value"),
                        .gas = message_gas(
                            *required_field(message, "gas", path + ".message"),
                            path + ".message.gas"),
                        .gas_price = message.contains("gasPrice")
                                         ? uint256(
                                               message.at("gasPrice"),
                                               path + ".message.gasPrice")
                                         : monad::uint256_t{},
                        .access_list = message.contains("accessList")
                                           ? access_list(
                                                 message.at("accessList"),
                                                 path + ".message.accessList")
                                           : monad::AccessList{}},
                .expected =
                    ExpectedResult{
                        .status = required_string(
                            expected, "status", path + ".expected"),
                        .output = bytes(
                            *required_field(
                                expected, "output", path + ".expected"),
                            path + ".expected.output"),
                        .gas_used = uint64(
                            *required_field(
                                expected, "gasUsed", path + ".expected"),
                            path + ".expected.gasUsed"),
                        .logs = expected.contains("logs")
                                    ? std::make_optional(logs(
                                          expected.at("logs"),
                                          path + ".expected.logs"))
                                    : std::nullopt,
                        .state = expected.contains("state")
                                     ? expected_state(
                                           expected.at("state"),
                                           path + ".expected.state")
                                     : std::vector<ExpectedAccount>{}},
                .metadata =
                    value.contains("metadata")
                        ? metadata(value.at("metadata"), path + ".metadata")
                        : CaseMetadata{}};
            if (parsed.name.empty()) {
                invalid(path + ".name", "must not be empty");
            }
            if (parsed.message.gas == 0 ||
                parsed.message.gas >
                    static_cast<std::uint64_t>(
                        std::numeric_limits<std::int64_t>::max())) {
                invalid(
                    path + ".message.gas", "must be between 1 and INT64_MAX");
            }
            if (parsed.expected.gas_used > parsed.message.gas) {
                invalid(
                    path + ".expected.gasUsed", "cannot exceed message gas");
            }
            if (parsed.expected.status != "success" &&
                parsed.expected.status != "revert") {
                invalid(
                    path + ".expected.status",
                    "supported values are success and revert");
            }
            auto const duplicate = std::find_if(
                suite.cases.begin(),
                suite.cases.end(),
                [&parsed](auto const &entry) {
                    return entry.name == parsed.name;
                });
            if (duplicate != suite.cases.end()) {
                invalid(path + ".name", "duplicate case name " + parsed.name);
            }
            suite.cases.push_back(std::move(parsed));
        }

        auto const provenance_path = normalized_directory / "provenance.json";
        auto const provenance = read_json(provenance_path);
        suite.provenance = validate_provenance(
            provenance,
            suite,
            manifest_payload,
            cases_payload,
            state_file_payload,
            state_payload,
            cases_name,
            state_name);

        return suite;
    }
}
