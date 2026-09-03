#pragma once

#include <category/core/address.hpp>
#include <category/core/byte_string.hpp>
#include <category/core/bytes.hpp>
#include <category/core/int.hpp>
#include <category/execution/ethereum/core/receipt.hpp>
#include <category/execution/ethereum/core/transaction.hpp>

#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace monad_execbench
{
    inline constexpr char schema_v1[] = "monad-execbench/v1";
    inline constexpr char default_execution_env[] = "MONAD_TEN";

    struct StorageSlot
    {
        monad::bytes32_t key{};
        monad::bytes32_t value{};
    };

    struct AccountFixture
    {
        monad::Address address{};
        monad::uint256_t balance{};
        std::uint64_t nonce{};
        monad::byte_string code{};
        monad::bytes32_t code_hash{};
        std::vector<StorageSlot> storage{};
    };

    struct BlockFixture
    {
        std::uint64_t number{};
        monad::bytes32_t hash{};
        monad::bytes32_t parent_hash{};
        std::uint64_t timestamp{};
        std::uint64_t gas_limit{};
        monad::uint256_t base_fee{};
        monad::Address beneficiary{};
        monad::bytes32_t prev_randao{};
        std::vector<std::pair<std::uint64_t, monad::bytes32_t>> block_hashes{};
    };

    struct MessageFixture
    {
        monad::Address sender{};
        monad::Address recipient{};
        monad::byte_string input{};
        monad::uint256_t value{};
        std::uint64_t gas{};
        monad::uint256_t gas_price{};
        monad::AccessList access_list{};
    };

    struct ExpectedAccount
    {
        monad::Address address{};
        std::optional<monad::uint256_t> balance{};
        std::optional<std::uint64_t> nonce{};
        std::optional<monad::byte_string> code{};
        std::vector<StorageSlot> storage{};
    };

    struct ExpectedResult
    {
        std::string status{};
        monad::byte_string output{};
        std::uint64_t gas_used{};
        std::optional<std::vector<monad::Receipt::Log>> logs{};
        std::vector<ExpectedAccount> state{};
    };

    struct ReplayCase
    {
        std::string name{};
        MessageFixture message{};
        ExpectedResult expected{};
    };

    struct FixtureSuite
    {
        std::filesystem::path directory{};
        std::string schema{};
        monad::uint256_t chain_id{};
        std::string execution_env{};
        BlockFixture block{};
        std::vector<AccountFixture> accounts{};
        std::vector<monad::Address> absent_accounts{};
        std::vector<ReplayCase> cases{};
    };

    FixtureSuite load_fixture_suite(std::filesystem::path const &directory);
}
