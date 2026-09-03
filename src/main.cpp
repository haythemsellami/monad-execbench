#include <category/core/bytes.hpp>
#include <category/vm/evm/traits.hpp>
#include <category/vm/runtime/types.hpp>
#include <category/vm/vm.hpp>

#include <CLI/CLI.hpp>
#include <evmc/evmc.h>
#include <evmc/mocked_host.hpp>

#include <algorithm>
#include <array>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <span>
#include <sstream>
#include <string>

namespace
{
    constexpr std::int64_t smoke_gas_limit = 1'000'000;

    std::string to_hex(std::uint8_t const *data, std::size_t const size)
    {
        std::ostringstream output;
        output << "0x" << std::hex << std::setfill('0');
        for (std::size_t i = 0; i < size; ++i) {
            output << std::setw(2) << static_cast<unsigned>(data[i]);
        }
        return output.str();
    }

    int run_monad_ten_smoke()
    {
        // PUSH1 0x2a; PUSH0; MSTORE; PUSH1 0x20; PUSH0; RETURN
        constexpr std::array<std::uint8_t, 8> bytecode{
            0x60, 0x2a, 0x5f, 0x52, 0x60, 0x20, 0x5f, 0xf3};
        auto const code = std::span<std::uint8_t const>{bytecode};

        monad::vm::VM vm{monad::vm::VM::Dual};
        evmc::MockedHost host;

        evmc_message message{};
        message.kind = EVMC_CALL;
        message.gas = smoke_gas_limit;

        monad::bytes32_t const code_hash{1};
        auto const varcode = vm.try_insert_varcode_raw(code_hash, code);
        auto runtime_context = monad::vm::runtime::Context::from(
            &host.get_interface(), host.to_context(), &message, code);

        auto const result = vm.execute_raw<monad::MonadTraits<MONAD_TEN>>(
            runtime_context, code_hash, varcode);

        bool const valid_output =
            result.output_size == 32 && result.output_data != nullptr &&
            std::all_of(
                result.output_data, result.output_data + 31,
                [](std::uint8_t const byte) { return byte == 0; }) &&
            result.output_data[31] == 0x2a;

        if (result.status_code != EVMC_SUCCESS || !valid_output) {
            std::cerr << "MONAD_TEN smoke execution failed"
                      << "\nstatus=" << result.status_code
                      << "\noutput="
                      << to_hex(result.output_data, result.output_size) << '\n';
            return 1;
        }

        std::cout << "execution_env=MONAD_TEN"
                  << "\nvm_mode=Dual"
                  << "\nmonad_commit=" << MONAD_EXECBENCH_MONAD_COMMIT
                  << "\nstatus=success"
                  << "\ngas_used=" << smoke_gas_limit - result.gas_left
                  << "\noutput="
                  << to_hex(result.output_data, result.output_size) << '\n';
        return 0;
    }
}

int main(int argc, char **argv)
{
    CLI::App app{
        "Replay and benchmark arbitrary EVM calls with Monad execution",
        "monad-execbench"};
    app.set_version_flag(
        "--version",
        std::string{MONAD_EXECBENCH_VERSION} + " (Monad " +
            MONAD_EXECBENCH_MONAD_COMMIT + ")");

    std::string execution_env{"MONAD_TEN"};
    auto *const smoke = app.add_subcommand(
        "smoke", "Run a production Monad VM integration smoke test");
    smoke->add_option(
             "--execution-env", execution_env,
             "Monad execution environment")
        ->capture_default_str();

    app.require_subcommand(0, 1);
    CLI11_PARSE(app, argc, argv);

    if (*smoke) {
        if (execution_env != "MONAD_TEN") {
            std::cerr << "unsupported execution environment: "
                      << execution_env << '\n';
            return 2;
        }
        return run_monad_ten_smoke();
    }

    std::cout << app.help();
    return 0;
}
