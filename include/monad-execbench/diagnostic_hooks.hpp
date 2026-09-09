#pragma once

#include <cstddef>
#include <cstdint>
#include <evmc/evmc.h>

namespace monad::vm::runtime
{
    struct Context;
}
namespace monad::vm::interpreter
{
    class Intercode;
}

namespace monad_execbench
{
    void diagnostic_enter(monad::vm::runtime::Context const &,
                          monad::vm::interpreter::Intercode const &) noexcept;
    void diagnostic_step(std::size_t pc, std::uint8_t opcode,
                         std::int64_t gas) noexcept;
    void diagnostic_exit(evmc_status_code status,
                         std::int64_t gas_left) noexcept;
} // namespace monad_execbench
