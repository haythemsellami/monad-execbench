// Pinned interpreter dispatch shim. Opcode implementations, runtime operations,
// and the stack-unwinding trampoline are supplied by the upstream library.
#include <category/vm/evm/explicit_traits.hpp>
#include <category/vm/interpreter/instruction_table.hpp>
#include <category/vm/interpreter/trampoline.hpp>
#include <monad-execbench/diagnostic_hooks.hpp>

#include <utility>

namespace monad::vm::interpreter
{
    namespace
    {
        using ProfileTraits = monad::MonadTraits<MONAD_TEN>;

        template <std::size_t Opcode>
        MONAD_VM_INSTRUCTION_CALL void
        profiled_instruction(runtime::Context &ctx, Intercode const &analysis,
                             uint256_t const *bottom, uint256_t *top,
                             std::int64_t gas, std::uint8_t const *pc);

        template <std::size_t... Opcodes>
        consteval InstrTable profiled_table(std::index_sequence<Opcodes...>)
        {
            return {profiled_instruction<Opcodes>...};
        }
    } // namespace

    template <>
    inline constexpr InstrTable instruction_table<ProfileTraits> =
        profiled_table(std::make_index_sequence<256>{});

    namespace
    {
        template <std::size_t Opcode>
        MONAD_VM_INSTRUCTION_CALL void
        profiled_instruction(runtime::Context &ctx, Intercode const &analysis,
                             uint256_t const *bottom, uint256_t *top,
                             std::int64_t gas, std::uint8_t const *pc)
        {
            monad_execbench::diagnostic_step(
                static_cast<std::size_t>(pc - analysis.code()), Opcode, gas);
            __attribute__((musttail)) return make_instruction_table<
                ProfileTraits>()[Opcode](ctx, analysis, bottom, top, gas, pc);
        }

        template <Traits traits>
        void core_loop(void *, runtime::Context *ctx, Intercode const *analysis,
                       uint256_t *stack, void *)
        {
            instruction_table<traits>[*analysis->code()](
                *ctx, *analysis, stack - 1, stack - 1, ctx->gas_remaining,
                analysis->code());
        }
    } // namespace

    template <Traits traits>
    void execute(runtime::Context &ctx, Intercode const &analysis,
                 std::uint8_t *stack)
    {
        if constexpr (std::is_same_v<traits, ProfileTraits>) {
            monad_execbench::diagnostic_enter(ctx, analysis);
        }
        trampoline(ctx, analysis, reinterpret_cast<uint256_t *>(stack),
                   core_loop<traits>);
    }

    EXPLICIT_TRAITS(execute);
} // namespace monad::vm::interpreter
