#include <monad-execbench/diagnostics.hpp>

#include <category/core/hex.hpp>
#include <ethash/keccak.hpp>

#include <bit>
#include <map>
#include <optional>
#include <stdexcept>
#include <vector>

namespace monad_execbench
{
    namespace
    {
        constexpr std::uint64_t max_steps = 10'000'000;
        constexpr std::size_t max_frames = 100'000;

        struct Counter
        {
            std::uint8_t opcode{};
            std::uint64_t count{};
            std::int64_t gas{};
        };

        struct Frame
        {
            std::optional<std::size_t> parent;
            std::int32_t depth{};
            std::string recipient;
            std::string sender;
            std::string selector;
            std::string code_hash;
            bool creation{};
            std::int64_t gas_supplied{};
            std::int64_t gas_used{};
            std::int64_t child_gas{};
            std::string status;
            std::optional<std::size_t> pending_pc;
            std::int64_t pending_gas{};
            std::int64_t pending_children{};
            std::map<std::size_t, Counter> pcs;

            void settle(std::int64_t gas_left)
            {
                if (pending_pc) {
                    auto const cost = pending_gas - gas_left - pending_children;
                    if (cost < 0) {
                        throw std::runtime_error{
                            "negative exclusive opcode gas"};
                    }
                    pcs.at(*pending_pc).gas += cost;
                }
                pending_children = 0;
            }
        };

        struct Collector
        {
            bool active{};
            bool failed{};
            std::uint64_t steps{};
            std::vector<Frame> frames;
            std::vector<std::size_t> stack;
            std::map<std::string, std::string> codes;
        };

        thread_local Collector collector;

        template <typename Function> void record(Function &&function) noexcept
        {
            if (!collector.active || collector.failed) {
                return;
            }
            // Exceptions must not cross the interpreter's assembly trampoline.
            try {
                function();
            } catch (...) {
                collector.failed = true;
            }
        }
    } // namespace

    void diagnostic_begin() { collector = Collector{.active = true}; }

    void
    diagnostic_enter(monad::vm::runtime::Context const &ctx,
                     monad::vm::interpreter::Intercode const &code) noexcept
    {
        record([&] {
            if (collector.frames.size() == max_frames) {
                throw std::runtime_error{"frame limit"};
            }
            auto const hash = std::bit_cast<monad::bytes32_t>(
                ethash::keccak256(code.code(), code.size()));
            auto const code_hash = "0x" + monad::to_hex(hash);
            collector.codes.try_emplace(
                code_hash, "0x" + monad::to_hex(monad::byte_string_view{
                                      code.code(), code.size()}));
            auto const parent = collector.stack.empty()
                                    ? std::optional<std::size_t>{}
                                    : collector.stack.back();
            bool creation = false;
            if (parent) {
                auto const &caller = collector.frames.at(*parent);
                if (!caller.pending_pc) {
                    throw std::runtime_error{
                        "child frame without calling opcode"};
                }
                auto const opcode = caller.pcs.at(*caller.pending_pc).opcode;
                creation = opcode == 0xf0 || opcode == 0xf5;
            }
            Frame frame{.parent = parent,
                        .depth = ctx.env.depth,
                        .recipient = "0x" + monad::to_hex(ctx.env.recipient),
                        .sender = "0x" + monad::to_hex(ctx.env.sender),
                        .selector =
                            ctx.env.input_data_size >= 4
                                ? "0x" + monad::to_hex(monad::byte_string_view{
                                             ctx.env.input_data, 4})
                                : "0x",
                        .code_hash = code_hash,
                        .creation = creation,
                        .gas_supplied = ctx.gas_remaining};
            collector.stack.push_back(collector.frames.size());
            collector.frames.push_back(std::move(frame));
        });
    }

    void diagnostic_step(std::size_t pc, std::uint8_t opcode,
                         std::int64_t gas) noexcept
    {
        record([&] {
            if (++collector.steps > max_steps || collector.stack.empty()) {
                throw std::runtime_error{"step limit or missing frame"};
            }
            auto &frame = collector.frames.at(collector.stack.back());
            frame.settle(gas);
            frame.pending_pc = pc;
            frame.pending_gas = gas;
            auto &counter = frame.pcs[pc];
            counter.opcode = opcode;
            ++counter.count;
        });
    }

    void diagnostic_exit(evmc_status_code status,
                         std::int64_t gas_left) noexcept
    {
        record([&] {
            if (collector.stack.empty()) {
                throw std::runtime_error{"VM result without interpreter frame"};
            }
            auto &frame = collector.frames.at(collector.stack.back());
            frame.settle(gas_left);
            frame.gas_used = frame.gas_supplied - gas_left;
            frame.status = status == EVMC_SUCCESS  ? "success"
                           : status == EVMC_REVERT ? "revert"
                                                   : "error";
            collector.stack.pop_back();
            if (frame.parent) {
                auto &parent = collector.frames.at(*frame.parent);
                parent.child_gas += frame.gas_used;
                parent.pending_children += frame.gas_used;
            }
        });
    }

    nlohmann::json diagnostic_finish(std::uint64_t verified_gas)
    {
        collector.active = false;
        if (collector.failed || !collector.stack.empty()) {
            throw std::runtime_error{"diagnostic collection failed "
                                     "(accounting, allocation, or limit: "
                                     "10,000,000 steps / 100,000 bytecode "
                                     "frames per case); no report produced"};
        }
        auto frames = nlohmann::json::array();
        std::int64_t attributed_gas{};
        for (std::size_t id = 0; id < collector.frames.size(); ++id) {
            auto const &frame = collector.frames[id];
            auto pcs = nlohmann::json::array();
            std::int64_t self_gas{};
            for (auto const &[pc, counter] : frame.pcs) {
                pcs.push_back({{"pc", pc},
                               {"opcode", counter.opcode},
                               {"count", counter.count},
                               {"gas", counter.gas}});
                self_gas += counter.gas;
            }
            if (self_gas != frame.gas_used - frame.child_gas) {
                throw std::runtime_error{
                    "diagnostic frame gas does not reconcile"};
            }
            attributed_gas += self_gas;
            frames.push_back(
                {{"id", id},
                 {"parent", frame.parent ? nlohmann::json(*frame.parent)
                                         : nlohmann::json(nullptr)},
                 {"depth", frame.depth},
                 {"recipient", frame.recipient},
                 {"sender", frame.sender},
                 {"selector", frame.selector},
                 {"code_hash", frame.code_hash},
                 {"code_kind", frame.creation ? "creation" : "runtime"},
                 {"gas_supplied", frame.gas_supplied},
                 {"gas_used", frame.gas_used},
                 {"self_gas", self_gas},
                 {"status", frame.status},
                 {"pcs", pcs}});
        }
        if (attributed_gas < 0 ||
            static_cast<std::uint64_t>(attributed_gas) > verified_gas) {
            throw std::runtime_error{"diagnostic case gas does not reconcile"};
        }
        return {{"gas_used", verified_gas},
                {"steps", collector.steps},
                {"outside_vm_gas",
                 verified_gas - static_cast<std::uint64_t>(attributed_gas)},
                {"codes", collector.codes},
                {"frames", frames}};
    }
} // namespace monad_execbench
