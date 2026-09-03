#include <monad-execbench/fixture.hpp>

#include <category/core/hex.hpp>
#include <category/core/keccak.hpp>

#include <nlohmann/json.hpp>
#include <zstd.h>

#include <algorithm>
#include <charconv>
#include <fstream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string_view>

namespace monad_execbench
{
    namespace
    {
        using json = nlohmann::json;

        [[noreturn]] void
        invalid(std::string const &path, std::string const &message)
        {
            throw std::runtime_error{
                "invalid fixture at " + path + ": " + message};
        }

        json read_json(std::filesystem::path const &path)
        {
            std::ifstream input{path, std::ios::binary};
            if (!input) {
                throw std::runtime_error{
                    "cannot open fixture file: " + path.string()};
            }

            std::string payload{
                std::istreambuf_iterator<char>{input},
                std::istreambuf_iterator<char>{}};
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
                if (size > 512ULL * 1024ULL * 1024ULL) {
                    throw std::runtime_error{
                        "fixture state exceeds 512 MiB: " + path.string()};
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

            try {
                return json::parse(payload);
            }
            catch (json::parse_error const &error) {
                throw std::runtime_error{
                    "cannot parse fixture file " + path.string() + ": " +
                    error.what()};
            }
        }

        std::string required_string(
            json const &object, char const *key, std::string const &path)
        {
            if (!object.is_object() || !object.contains(key) ||
                !object.at(key).is_string()) {
                invalid(path + "." + key, "expected a string");
            }
            return object.at(key).get<std::string>();
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
            if (!value.is_string()) {
                invalid(
                    path, "expected a decimal or 0x-prefixed integer string");
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
                if (!entry.is_object() || !entry.contains("storageKeys") ||
                    !entry.at("storageKeys").is_array()) {
                    invalid(
                        entry_path, "expected address and storageKeys array");
                }
                monad::AccessEntry parsed{
                    .a = fixed_hex<monad::Address>(
                        entry.at("address"), entry_path + ".address")};
                for (std::size_t j = 0; j < entry.at("storageKeys").size();
                     ++j) {
                    parsed.keys.push_back(fixed_hex<monad::bytes32_t>(
                        entry.at("storageKeys").at(j),
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
                if (!entry.is_object() || !entry.contains("topics") ||
                    !entry.at("topics").is_array()) {
                    invalid(
                        entry_path, "expected address, data, and topics array");
                }
                monad::Receipt::Log log{
                    .data = bytes(entry.at("data"), entry_path + ".data"),
                    .topics = {},
                    .address = fixed_hex<monad::Address>(
                        entry.at("address"), entry_path + ".address")};
                for (std::size_t j = 0; j < entry.at("topics").size(); ++j) {
                    log.topics.push_back(fixed_hex<monad::bytes32_t>(
                        entry.at("topics").at(j),
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

        auto const manifest = read_json(normalized_directory / "manifest.json");
        FixtureSuite suite{
            .directory = normalized_directory,
            .schema = required_string(manifest, "schema", "manifest")};
        if (suite.schema != schema_v1) {
            invalid("manifest.schema", "unsupported schema " + suite.schema);
        }

        if (!manifest.contains("chain") || !manifest.at("chain").is_object()) {
            invalid("manifest.chain", "expected an object");
        }
        auto const &chain = manifest.at("chain");
        suite.chain_id = uint256(chain.at("chainId"), "manifest.chain.chainId");
        suite.execution_env =
            required_string(chain, "executionEnv", "manifest.chain");

        if (!manifest.contains("block") || !manifest.at("block").is_object()) {
            invalid("manifest.block", "expected an object");
        }
        auto const &block = manifest.at("block");
        suite.block.number =
            uint64(block.at("number"), "manifest.block.number");
        suite.block.hash = fixed_hex<monad::bytes32_t>(
            block.at("hash"), "manifest.block.hash");
        suite.block.parent_hash = fixed_hex<monad::bytes32_t>(
            block.at("parentHash"), "manifest.block.parentHash");
        suite.block.timestamp =
            uint64(block.at("timestamp"), "manifest.block.timestamp");
        suite.block.gas_limit =
            uint64(block.at("gasLimit"), "manifest.block.gasLimit");
        suite.block.base_fee =
            uint256(block.at("baseFee"), "manifest.block.baseFee");
        suite.block.beneficiary = fixed_hex<monad::Address>(
            block.at("beneficiary"), "manifest.block.beneficiary");
        suite.block.prev_randao = fixed_hex<monad::bytes32_t>(
            block.at("prevRandao"), "manifest.block.prevRandao");
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

        auto const state_json = read_json(referenced_file(
            normalized_directory, manifest, "state", "state.json.zst"));
        if (!state_json.is_object() || !state_json.contains("accounts") ||
            !state_json.at("accounts").is_object()) {
            invalid("state.accounts", "expected an object");
        }
        for (auto const &[address_text, account] :
             state_json.at("accounts").items()) {
            auto const account_path = "state.accounts." + address_text;
            if (!account.is_object()) {
                invalid(account_path, "expected an object");
            }
            json const address_json = address_text;
            AccountFixture parsed{
                .address =
                    fixed_hex<monad::Address>(address_json, account_path),
                .balance =
                    uint256(account.at("balance"), account_path + ".balance"),
                .nonce = uint64(account.at("nonce"), account_path + ".nonce"),
                .code = bytes(account.at("code"), account_path + ".code"),
                .code_hash = {},
                .storage =
                    storage(account.at("storage"), account_path + ".storage")};
            parsed.code_hash = monad::to_bytes(monad::keccak256(parsed.code));
            auto const declared = fixed_hex<monad::bytes32_t>(
                account.at("codeHash"), account_path + ".codeHash");
            if (declared != parsed.code_hash) {
                invalid(
                    account_path + ".codeHash",
                    "does not match runtime code");
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

        auto const cases_json = read_json(referenced_file(
            normalized_directory, manifest, "cases", "cases.json"));
        if (!cases_json.is_array() || cases_json.empty()) {
            invalid("cases", "expected a non-empty array");
        }
        for (std::size_t i = 0; i < cases_json.size(); ++i) {
            auto const &value = cases_json.at(i);
            auto const path = "cases[" + std::to_string(i) + "]";
            if (!value.is_object() || !value.contains("message") ||
                !value.at("message").is_object() ||
                !value.contains("expected") ||
                !value.at("expected").is_object()) {
                invalid(path, "expected name, message, and expected objects");
            }
            auto const &message = value.at("message");
            auto const &expected = value.at("expected");
            ReplayCase parsed{
                .name = required_string(value, "name", path),
                .message =
                    MessageFixture{
                        .sender = fixed_hex<monad::Address>(
                            message.at("from"), path + ".message.from"),
                        .recipient = fixed_hex<monad::Address>(
                            message.at("to"), path + ".message.to"),
                        .input =
                            bytes(message.at("input"), path + ".message.input"),
                        .value = uint256(
                            message.at("value"), path + ".message.value"),
                        .gas = uint64(message.at("gas"), path + ".message.gas"),
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
                .expected = ExpectedResult{
                    .status =
                        required_string(expected, "status", path + ".expected"),
                    .output =
                        bytes(expected.at("output"), path + ".expected.output"),
                    .gas_used = uint64(
                        expected.at("gasUsed"), path + ".expected.gasUsed"),
                    .logs =
                        expected.contains("logs")
                            ? std::make_optional(logs(
                                  expected.at("logs"), path + ".expected.logs"))
                            : std::nullopt,
                    .state = expected.contains("state")
                                 ? expected_state(
                                       expected.at("state"),
                                       path + ".expected.state")
                                 : std::vector<ExpectedAccount>{}}};
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
        if (!provenance.is_object()) {
            invalid("provenance", "expected an object");
        }

        return suite;
    }
}
