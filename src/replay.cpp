#include <monad-execbench/replay.hpp>

#include <category/core/hex.hpp>
#include <category/execution/ethereum/block_hash_buffer.hpp>
#include <category/execution/ethereum/core/block.hpp>
#include <category/execution/ethereum/core/transaction.hpp>
#include <category/execution/ethereum/db/db.hpp>
#include <category/execution/ethereum/db/test/commit_simple.hpp>
#include <category/execution/ethereum/db/trie_db.hpp>
#include <category/execution/ethereum/db/util.hpp>
#include <category/execution/ethereum/evmc_host.hpp>
#include <category/execution/ethereum/execute_message.hpp>
#include <category/execution/ethereum/reserve_balance.hpp>
#include <category/execution/ethereum/state2/block_state.hpp>
#include <category/execution/ethereum/state3/state.hpp>
#include <category/execution/ethereum/trace/call_tracer.hpp>
#include <category/execution/ethereum/trace/state_tracer.hpp>
#include <category/execution/ethereum/tx_context.hpp>
#include <category/execution/ethereum/types/incarnation.hpp>
#include <category/execution/monad/chain/monad_chain.hpp>
#include <category/execution/monad/chain/monad_mainnet.hpp>
#include <category/vm/evm/delegation.hpp>
#include <category/vm/evm/traits.hpp>
#include <category/vm/vm.hpp>

#include <evmc/evmc.h>
#include <evmc/evmc.hpp>

#include <algorithm>
#include <cstdint>
#include <functional>
#include <limits>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <variant>
#include <vector>

namespace monad_execbench
{
    namespace
    {
        using Traits = monad::MonadTraits<MONAD_TEN>;

        std::string hex(monad::Address const &value)
        {
            return "0x" + monad::to_hex(value);
        }

        std::string hex(monad::bytes32_t const &value)
        {
            return "0x" + monad::to_hex(value);
        }

        std::string hex(monad::byte_string const &value)
        {
            return "0x" + monad::to_hex(value);
        }

        template <typename T, typename Predicate>
        bool contains(std::vector<T> const &values, Predicate predicate)
        {
            return std::find_if(values.begin(), values.end(), predicate) !=
                   values.end();
        }

        AccountFixture const *
        find_account(FixtureSuite const &suite, monad::Address const &address)
        {
            auto const found = std::find_if(
                suite.accounts.begin(),
                suite.accounts.end(),
                [&address](auto const &account) {
                    return account.address == address;
                });
            return found == suite.accounts.end() ? nullptr : &*found;
        }

        class ValidatingDb final : public monad::Db
        {
            monad::Db &inner_;
            FixtureSuite const &suite_;
            std::vector<std::string> missing_{};

            void add_missing(std::string message)
            {
                if (!contains(missing_, [&message](auto const &entry) {
                        return entry == message;
                    })) {
                    missing_.push_back(std::move(message));
                }
            }

        public:
            ValidatingDb(monad::Db &inner, FixtureSuite const &suite)
                : inner_{inner}
                , suite_{suite}
            {
            }

            std::vector<std::string> const &missing() const
            {
                return missing_;
            }

            bool is_page_encoded() const override
            {
                return inner_.is_page_encoded();
            }

            std::optional<monad::Account>
            read_account(monad::Address const &address) override
            {
                auto const known_absent = contains(
                    suite_.absent_accounts,
                    [&address](auto const &entry) { return entry == address; });
                if (find_account(suite_, address) == nullptr && !known_absent) {
                    add_missing("uncaptured account " + hex(address));
                }
                return inner_.read_account(address);
            }

            monad::bytes32_t read_storage(
                monad::Address const &address, monad::Incarnation incarnation,
                monad::bytes32_t const &key) override
            {
                auto const *account = find_account(suite_, address);
                if (account == nullptr) {
                    add_missing(
                        "uncaptured storage " + hex(address) + "[" + hex(key) +
                        "]");
                }
                else if (!contains(account->storage, [&key](auto const &slot) {
                             return slot.key == key;
                         })) {
                    add_missing(
                        "uncaptured storage " + hex(address) + "[" + hex(key) +
                        "] (code hash " + hex(account->code_hash) + ")");
                }
                return inner_.read_storage(address, incarnation, key);
            }

            monad::storage_page_t read_storage_page(
                monad::Address const &address, monad::Incarnation incarnation,
                monad::bytes32_t const &page_key) override
            {
                return inner_.read_storage_page(address, incarnation, page_key);
            }

            monad::vm::SharedIntercode
            read_code(monad::bytes32_t const &code_hash) override
            {
                if (!contains(
                        suite_.accounts, [&code_hash](auto const &account) {
                            return account.code_hash == code_hash;
                        })) {
                    add_missing(
                        "uncaptured runtime code with hash " + hex(code_hash));
                }
                return inner_.read_code(code_hash);
            }

            monad::BlockHeader read_eth_header() override
            {
                return inner_.read_eth_header();
            }

            monad::bytes32_t state_root() override
            {
                return inner_.state_root();
            }

            monad::bytes32_t receipts_root() override
            {
                return inner_.receipts_root();
            }

            monad::bytes32_t transactions_root() override
            {
                return inner_.transactions_root();
            }

            std::optional<monad::bytes32_t> withdrawals_root() override
            {
                return inner_.withdrawals_root();
            }

            void set_block_and_prefix(
                std::uint64_t block_number,
                monad::bytes32_t const &block_id) override
            {
                inner_.set_block_and_prefix(block_number, block_id);
            }

            void finalize(
                std::uint64_t block_number,
                monad::bytes32_t const &block_id) override
            {
                inner_.finalize(block_number, block_id);
            }

            void update_verified_block(std::uint64_t block_number) override
            {
                inner_.update_verified_block(block_number);
            }

            void update_voted_metadata(
                std::uint64_t block_number,
                monad::bytes32_t const &block_id) override
            {
                inner_.update_voted_metadata(block_number, block_id);
            }

            void update_proposed_metadata(
                std::uint64_t block_number,
                monad::bytes32_t const &block_id) override
            {
                inner_.update_proposed_metadata(block_number, block_id);
            }

            std::uint64_t get_block_number() const override
            {
                return inner_.get_block_number();
            }

            void commit(
                monad::bytes32_t const &block_id, monad::CommitBuilder &builder,
                monad::BlockHeader const &header,
                monad::StateDeltas const &state_deltas,
                std::function<void(monad::BlockHeader &)> populate_header_fn)
                override
            {
                inner_.commit(
                    block_id,
                    builder,
                    header,
                    state_deltas,
                    std::move(populate_header_fn));
            }

            std::string print_stats() override
            {
                return inner_.print_stats();
            }
        };

        class FixtureBlockHashBuffer final : public monad::BlockHashBuffer
        {
            BlockFixture const &block_;
            mutable std::vector<std::string> missing_{};
            monad::bytes32_t missing_hash_{[] {
                monad::bytes32_t value{};
                value.bytes[31] = 1;
                return value;
            }()};

        public:
            explicit FixtureBlockHashBuffer(BlockFixture const &block)
                : block_{block}
            {
            }

            std::uint64_t n() const override
            {
                return block_.number;
            }

            monad::bytes32_t const &get(std::uint64_t number) const override
            {
                auto const found = std::find_if(
                    block_.block_hashes.begin(),
                    block_.block_hashes.end(),
                    [number](auto const &entry) {
                        return entry.first == number;
                    });
                if (found != block_.block_hashes.end()) {
                    return found->second;
                }
                auto const message =
                    "uncaptured block hash " + std::to_string(number);
                if (!contains(missing_, [&message](auto const &entry) {
                        return entry == message;
                    })) {
                    missing_.push_back(message);
                }
                return missing_hash_;
            }

            std::vector<std::string> const &missing() const
            {
                return missing_;
            }
        };

        struct BaseState
        {
            monad::mpt::Db db{std::make_unique<monad::MonadInMemoryMachine>()};
            monad::TrieDb trie_db{db};
        };

        std::unique_ptr<BaseState> build_base_state(FixtureSuite const &suite)
        {
            auto base = std::make_unique<BaseState>();
            monad::vm::VM setup_vm{monad::vm::VM::InterpreterOnly};
            monad::BlockState block_state{base->trie_db, setup_vm};
            monad::State state{block_state, monad::Incarnation{0, 0}};

            for (auto const &account : suite.accounts) {
                state.add_to_balance(account.address, account.balance);
                state.set_nonce(account.address, account.nonce);
                if (!account.code.empty()) {
                    state.set_code(account.address, account.code);
                }
                for (auto const &slot : account.storage) {
                    state.set_storage(account.address, slot.key, slot.value);
                }
            }

            block_state.merge(state);
            auto released = std::move(block_state).release();
            monad::BlockHeader base_header{.number = 0};
            monad::test::commit_simple(
                base->trie_db,
                *released.state,
                released.code,
                monad::NULL_HASH_BLAKE3,
                base_header);
            base->trie_db.finalize(0, monad::NULL_HASH_BLAKE3);
            return base;
        }

        monad::BlockHeader make_header(FixtureSuite const &suite)
        {
            return monad::BlockHeader{
                .prev_randao = suite.block.prev_randao,
                .number = suite.block.number,
                .gas_limit = suite.block.gas_limit,
                .timestamp = suite.block.timestamp,
                .beneficiary = suite.block.beneficiary,
                .base_fee_per_gas = suite.block.base_fee};
        }

        monad::Transaction make_transaction(ReplayCase const &replay_case)
        {
            return monad::Transaction{
                .max_fee_per_gas = replay_case.message.gas_price,
                .gas_limit = replay_case.message.gas,
                .value = replay_case.message.value,
                .to = replay_case.message.recipient,
                .type = monad::TransactionType::legacy,
                .data = replay_case.message.input,
                .access_list = replay_case.message.access_list};
        }

        struct ReplayHost
        {
            using AddressSet =
                ankerl::unordered_dense::segmented_set<monad::Address>;

            static AddressSet const &empty_sender_set()
            {
                static AddressSet const empty{};
                return empty;
            }

            monad::NoopCallTracer call_tracer{};
            monad::trace::StateTracer state_tracer{std::monostate{}};
            evmc_tx_context tx_context{};
            std::vector<monad::Address> senders{};
            std::vector<std::vector<std::optional<monad::Address>>>
                authorities{};
            AddressSet senders_and_authorities{};
            monad::ChainContext<Traits> chain_context;
            monad::EvmcHost<Traits> host;

            ReplayHost(
                monad::BlockHashBuffer const &block_hash_buffer,
                monad::State &state, monad::Transaction const &transaction,
                monad::Address const &sender, monad::BlockHeader const &header,
                monad::uint256_t const &chain_id,
                monad::MonadMainnet const &chain)
                : tx_context{monad::get_tx_context<Traits>(
                      transaction, sender, header, chain_id,
                      chain.get_blob_schedule(header.timestamp))}
                , senders{sender}
                , authorities(1)
                , senders_and_authorities{monad::
                                              combine_senders_and_authorities(
                                                  senders, authorities)}
                , chain_context{.grandparent_senders_and_authorities = empty_sender_set(), .parent_senders_and_authorities = empty_sender_set(), .senders_and_authorities = senders_and_authorities, .senders = senders, .authorities = authorities}
                , host{
                      call_tracer,
                      state_tracer,
                      tx_context,
                      block_hash_buffer,
                      state,
                      transaction,
                      header.base_fee_per_gas,
                      0,
                      chain_context}
            {
            }
        };

        struct ReplayResult
        {
            evmc_status_code status{};
            monad::byte_string output{};
            std::uint64_t gas_used{};
            std::vector<monad::Receipt::Log> logs{};
            std::vector<std::string> failures{};
        };

        std::string status_name(evmc_status_code status)
        {
            if (status == EVMC_SUCCESS) {
                return "success";
            }
            if (status == EVMC_REVERT) {
                return "revert";
            }
            return "evmc-status-" + std::to_string(static_cast<int>(status));
        }

        void verify_expected_state(
            ReplayCase const &replay_case, monad::State &state,
            std::vector<std::string> &failures)
        {
            for (auto const &expected : replay_case.expected.state) {
                auto const prefix = "state " + hex(expected.address);
                if (!state.account_exists(expected.address)) {
                    failures.push_back(prefix + " expected account is absent");
                    continue;
                }
                if (expected.balance &&
                    state.get_balance(expected.address) != *expected.balance) {
                    failures.push_back(prefix + " balance mismatch");
                }
                if (expected.nonce &&
                    state.get_nonce(expected.address) != *expected.nonce) {
                    failures.push_back(prefix + " nonce mismatch");
                }
                if (expected.code) {
                    auto const size = state.get_code_size(expected.address);
                    monad::byte_string actual(size, 0);
                    state.copy_code(
                        expected.address, 0, actual.data(), actual.size());
                    if (actual != *expected.code) {
                        failures.push_back(prefix + " runtime code mismatch");
                    }
                }
                for (auto const &slot : expected.storage) {
                    if (state.get_storage(expected.address, slot.key) !=
                        slot.value) {
                        failures.push_back(
                            prefix + " storage " + hex(slot.key) + " mismatch");
                    }
                }
            }
        }

        monad::vm::VM::Mode vm_mode(BenchmarkMode const mode)
        {
            switch (mode) {
            case BenchmarkMode::dual_hot:
                return monad::vm::VM::Dual;
            case BenchmarkMode::interpreter_hot:
                return monad::vm::VM::InterpreterOnly;
            }
            throw std::runtime_error{"unsupported benchmark mode"};
        }

        void prime_code_cache(
            monad::vm::VM &vm, FixtureSuite const &suite,
            BenchmarkMode const mode)
        {
            std::vector<std::pair<monad::bytes32_t, monad::vm::SharedVarcode>>
                varcodes;
            varcodes.reserve(suite.accounts.size());
            for (auto const &account : suite.accounts) {
                if (account.code.empty()) {
                    continue;
                }
                varcodes.emplace_back(
                    account.code_hash,
                    vm.try_insert_varcode_raw(account.code_hash, account.code));
            }

            if (mode == BenchmarkMode::dual_hot) {
                for (auto const &[code_hash, varcode] : varcodes) {
                    (void)vm.compiler().cached_compile<Traits>(
                        code_hash, varcode->intercode(), vm.compiler_config());
                }
            }
            else {
                for (auto const &[code_hash, varcode] : varcodes) {
                    (void)vm.compiler().async_compile<Traits>(
                        code_hash, varcode->intercode(), vm.compiler_config());
                }
                vm.compiler().debug_wait_for_empty_queue();
            }
        }

        struct ExecutionSession
        {
            std::unique_ptr<BaseState> base;
            monad::vm::VM vm;

            ExecutionSession(
                FixtureSuite const &suite, BenchmarkMode const mode)
                : base{build_base_state(suite)}
                , vm{vm_mode(mode)}
            {
                prime_code_cache(vm, suite, mode);
            }
        };

        class ExecutionIteration
        {
            FixtureSuite const &suite_;
            ReplayCase const &replay_case_;
            ExecutionSession &session_;
            std::unique_ptr<ValidatingDb> validating_db_;
            monad::BlockState block_state_;
            monad::State state_;
            monad::BlockHeader header_;
            monad::Transaction transaction_;
            monad::MonadMainnet chain_{};
            FixtureBlockHashBuffer block_hash_buffer_;
            ReplayHost replay_host_;
            monad::vm::MemoryPool::Ref message_memory_;
            evmc_message message_{};
            std::optional<evmc::Result> result_{};

        public:
            ExecutionIteration(
                FixtureSuite const &suite, ReplayCase const &replay_case,
                ExecutionSession &session, bool const validate_reads)
                : suite_{suite}
                , replay_case_{replay_case}
                , session_{session}
                , validating_db_{
                      validate_reads
                          ? std::make_unique<ValidatingDb>(
                                session.base->trie_db, suite)
                          : nullptr}
                , block_state_{
                      validating_db_
                          ? static_cast<monad::Db &>(*validating_db_)
                          : static_cast<monad::Db &>(session.base->trie_db),
                      session.vm}
                , state_{
                      block_state_,
                      monad::Incarnation{suite.block.number, 0}}
                , header_{make_header(suite)}
                , transaction_{make_transaction(replay_case)}
                , block_hash_buffer_{suite.block}
                , replay_host_{
                      block_hash_buffer_,
                      state_,
                      transaction_,
                      replay_case.message.sender,
                      header_,
                      suite.chain_id,
                      chain_}
                , message_memory_{session.vm.message_memory_ref()}
            {
                monad::init_reserve_balance_context<Traits>(
                    state_,
                    replay_case.message.sender,
                    transaction_,
                    header_.base_fee_per_gas,
                    0,
                    replay_host_.state_tracer,
                    replay_host_.chain_context);

                replay_host_.host.access_account(header_.beneficiary);
                state_.access_account(replay_case.message.sender);
                for (auto const &entry : transaction_.access_list) {
                    state_.access_account(entry.a);
                    for (auto const &key : entry.keys) {
                        state_.access_storage<Traits>(entry.a, key);
                    }
                }
                state_.access_account(replay_case.message.recipient);

                if (replay_case.message.gas >
                    static_cast<std::uint64_t>(
                        std::numeric_limits<std::int64_t>::max())) {
                    throw std::runtime_error{
                        "case " + replay_case.name +
                        ": gas limit exceeds the EVMC signed gas range"};
                }

                message_ = evmc_message{
                    .kind = EVMC_CALL,
                    .flags = 0,
                    .depth = 0,
                    .gas = static_cast<std::int64_t>(replay_case.message.gas),
                    .recipient = replay_case.message.recipient,
                    .sender = replay_case.message.sender,
                    .input_data = replay_case.message.input.data(),
                    .input_size = replay_case.message.input.size(),
                    .value = monad::store_be_as<evmc::uint256be>(
                        replay_case.message.value),
                    .create2_salt = {},
                    .code_address = replay_case.message.recipient,
                    .memory_handle = message_memory_.get(),
                    .memory = message_memory_.get(),
                    .memory_capacity = session.vm.message_memory_capacity()};

                if (auto const delegate = monad::vm::evm::resolve_delegation(
                        &replay_host_.host.get_interface(),
                        replay_host_.host.to_context(),
                        replay_case.message.recipient)) {
                    message_.code_address = *delegate;
                    message_.flags |= EVMC_DELEGATED;
                    state_.access_account(*delegate);
                }
            }

            void execute()
            {
                if (result_) {
                    throw std::logic_error{
                        "benchmark iteration has already executed"};
                }
                result_.emplace(monad::execute_call_message<Traits>(
                    &replay_host_.host, state_, message_));
            }

            ReplayResult validate()
            {
                if (!result_) {
                    throw std::logic_error{
                        "benchmark iteration has not executed"};
                }
                if (result_->gas_left < 0 || result_->gas_left > message_.gas) {
                    throw std::runtime_error{
                        "case " + replay_case_.name +
                        ": execution returned gas_left outside the valid "
                        "range"};
                }

                auto const gas_left =
                    static_cast<std::uint64_t>(result_->gas_left);
                auto output_bytes = monad::byte_string{};
                if (result_->output_size != 0) {
                    if (result_->output_data == nullptr) {
                        throw std::runtime_error{
                            "case " + replay_case_.name +
                            ": execution returned null output data"};
                    }
                    output_bytes.assign(
                        result_->output_data,
                        result_->output_data + result_->output_size);
                }
                ReplayResult replay_result{
                    .status = result_->status_code,
                    .output = std::move(output_bytes),
                    .gas_used = replay_case_.message.gas - gas_left,
                    .logs = {state_.logs().begin(), state_.logs().end()},
                    .failures = {}};

                if (status_name(replay_result.status) !=
                    replay_case_.expected.status) {
                    replay_result.failures.push_back(
                        "status mismatch: expected " +
                        replay_case_.expected.status + ", got " +
                        status_name(replay_result.status));
                }
                if (replay_result.output != replay_case_.expected.output) {
                    replay_result.failures.push_back(
                        "output mismatch: expected " +
                        hex(replay_case_.expected.output) + ", got " +
                        hex(replay_result.output));
                }
                if (replay_result.gas_used != replay_case_.expected.gas_used) {
                    replay_result.failures.push_back(
                        "gas mismatch: expected " +
                        std::to_string(replay_case_.expected.gas_used) +
                        ", got " + std::to_string(replay_result.gas_used));
                }
                if (replay_case_.expected.logs &&
                    replay_result.logs != *replay_case_.expected.logs) {
                    replay_result.failures.push_back("logs mismatch");
                }
                verify_expected_state(
                    replay_case_, state_, replay_result.failures);
                if (validating_db_) {
                    replay_result.failures.insert(
                        replay_result.failures.end(),
                        validating_db_->missing().begin(),
                        validating_db_->missing().end());
                }
                replay_result.failures.insert(
                    replay_result.failures.end(),
                    block_hash_buffer_.missing().begin(),
                    block_hash_buffer_.missing().end());
                return replay_result;
            }
        };

        ReplayResult execute_case(
            FixtureSuite const &suite, ReplayCase const &replay_case,
            ExecutionSession &session, bool const validate_reads)
        {
            ExecutionIteration iteration{
                suite, replay_case, session, validate_reads};
            iteration.execute();
            return iteration.validate();
        }

        void fail_case(
            ReplayCase const &replay_case, std::string const &mode,
            std::vector<std::string> const &failures)
        {
            std::ostringstream message;
            message << "case '" << replay_case.name << "' failed in " << mode;
            for (auto const &failure : failures) {
                message << "\n  - " << failure;
            }
            throw std::runtime_error{message.str()};
        }

        FixtureSuite const &require_supported_suite(FixtureSuite const &suite)
        {
            if (suite.execution_env != default_execution_env) {
                throw std::runtime_error{
                    "unsupported execution environment: " +
                    suite.execution_env};
            }
            return suite;
        }
    }

    struct BenchmarkSession::Impl
    {
        FixtureSuite const &suite;
        BenchmarkMode mode;
        ExecutionSession session;

        Impl(FixtureSuite const &fixture_suite, BenchmarkMode const mode_value)
            : suite{require_supported_suite(fixture_suite)}
            , mode{mode_value}
            , session{suite, mode}
        {
        }
    };

    struct BenchmarkIteration::Impl
    {
        ReplayCase const &replay_case;
        BenchmarkMode mode;
        std::unique_ptr<ExecutionIteration> execution;

        Impl(
            ReplayCase const &case_value, BenchmarkMode const mode_value,
            std::unique_ptr<ExecutionIteration> iteration)
            : replay_case{case_value}
            , mode{mode_value}
            , execution{std::move(iteration)}
        {
        }
    };

    std::string_view benchmark_mode_name(BenchmarkMode const mode)
    {
        switch (mode) {
        case BenchmarkMode::dual_hot:
            return "dual-hot";
        case BenchmarkMode::interpreter_hot:
            return "interpreter-hot";
        }
        throw std::runtime_error{"unsupported benchmark mode"};
    }

    BenchmarkIteration::BenchmarkIteration(std::unique_ptr<Impl> impl)
        : impl_{std::move(impl)}
    {
    }

    BenchmarkIteration::~BenchmarkIteration() = default;
    BenchmarkIteration::BenchmarkIteration(BenchmarkIteration &&) noexcept =
        default;
    BenchmarkIteration &
    BenchmarkIteration::operator=(BenchmarkIteration &&) noexcept = default;

    void BenchmarkIteration::execute()
    {
        impl_->execution->execute();
    }

    BenchmarkSample BenchmarkIteration::validate()
    {
        auto const result = impl_->execution->validate();
        if (!result.failures.empty()) {
            fail_case(
                impl_->replay_case,
                std::string{benchmark_mode_name(impl_->mode)},
                result.failures);
        }
        return BenchmarkSample{
            .gas_used = result.gas_used,
            .output_size = result.output.size(),
            .log_count = result.logs.size()};
    }

    BenchmarkSession::BenchmarkSession(
        FixtureSuite const &suite, BenchmarkMode const mode)
        : impl_{std::make_unique<Impl>(suite, mode)}
    {
    }

    BenchmarkSession::~BenchmarkSession() = default;
    BenchmarkSession::BenchmarkSession(BenchmarkSession &&) noexcept = default;
    BenchmarkSession &
    BenchmarkSession::operator=(BenchmarkSession &&) noexcept = default;

    BenchmarkIteration BenchmarkSession::prepare(ReplayCase const &replay_case)
    {
        auto const belongs_to_suite = std::any_of(
            impl_->suite.cases.begin(),
            impl_->suite.cases.end(),
            [&replay_case](auto const &candidate) {
                return std::addressof(candidate) == std::addressof(replay_case);
            });
        if (!belongs_to_suite) {
            throw std::invalid_argument{
                "benchmark case does not belong to the prepared suite"};
        }
        return BenchmarkIteration{std::make_unique<BenchmarkIteration::Impl>(
            replay_case,
            impl_->mode,
            std::make_unique<ExecutionIteration>(
                impl_->suite, replay_case, impl_->session, false))};
    }

    VerificationSummary verify_fixture_suite(
        FixtureSuite const &suite,
        std::optional<std::string> const &execution_env, std::ostream &output)
    {
        auto const selected_environment =
            execution_env.value_or(suite.execution_env);
        if (selected_environment != suite.execution_env) {
            throw std::runtime_error{
                "execution environment " + selected_environment +
                " does not match fixture environment " + suite.execution_env};
        }
        if (selected_environment != default_execution_env) {
            throw std::runtime_error{
                "unsupported execution environment: " + selected_environment};
        }

        ExecutionSession interpreter_session{
            suite, BenchmarkMode::interpreter_hot};
        ExecutionSession dual_session{suite, BenchmarkMode::dual_hot};

        for (auto const &replay_case : suite.cases) {
            auto const interpreter =
                execute_case(suite, replay_case, interpreter_session, true);
            if (!interpreter.failures.empty()) {
                fail_case(replay_case, "interpreter-hot", interpreter.failures);
            }

            auto const dual =
                execute_case(suite, replay_case, dual_session, true);
            if (!dual.failures.empty()) {
                fail_case(replay_case, "dual-hot", dual.failures);
            }
            if (interpreter.status != dual.status ||
                interpreter.output != dual.output ||
                interpreter.gas_used != dual.gas_used ||
                interpreter.logs != dual.logs) {
                throw std::runtime_error{
                    "case '" + replay_case.name +
                    "' differs between InterpreterOnly and Dual"};
            }

            output << "case=" << replay_case.name
                   << " status=verified gas_used=" << dual.gas_used << "\n";
        }

        output << "execution_env=" << selected_environment << "\n"
               << "monad_commit=" << MONAD_EXECBENCH_MONAD_COMMIT << "\n"
               << "cases=" << suite.cases.size() << "\n"
               << "verification=passed\n";
        return VerificationSummary{.cases = suite.cases.size()};
    }
}
