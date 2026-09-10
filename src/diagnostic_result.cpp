#include <category/vm/runtime/types.hpp>
#include <monad-execbench/diagnostic_hooks.hpp>

static_assert(MONAD_TEN == 10);

// GNU ld wraps the pinned MONAD_TEN Context::copy_to_evmc_result symbol.
// The upstream finalizer remains responsible for return-memory expansion and
// exceptional-halt accounting; observe its result without duplicating that
// logic.
evmc::Result real_copy_result(monad::vm::runtime::Context *) asm(
    "__real_" MONAD_EXECBENCH_RESULT_SYMBOL);
evmc::Result wrapped_copy_result(monad::vm::runtime::Context *) asm(
    "__wrap_" MONAD_EXECBENCH_RESULT_SYMBOL);

evmc::Result wrapped_copy_result(monad::vm::runtime::Context *ctx)
{
    auto result = real_copy_result(ctx);
    monad_execbench::diagnostic_exit(result.status_code, result.gas_left);
    return result;
}
