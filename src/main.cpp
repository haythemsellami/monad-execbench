#include <category/core/bytes.hpp>
#include <category/vm/evm/traits.hpp>
#include <category/vm/runtime/types.hpp>
#include <category/vm/vm.hpp>

#include <ethash/keccak.hpp>

#include <evmc/evmc.h>
#include <evmc/mocked_host.hpp>

#include <algorithm>
#include <array>
#include <bit>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <span>
#include <sstream>
#include <string>
#include <string_view>

namespace
{
    constexpr std::int64_t smoke_gas_limit = 1'000'000;

    void print_usage(std::ostream &output)
    {
        output << "Usage:\n"
               << "  monad-execbench --help\n"
               << "  monad-execbench --version\n"
               << "  monad-execbench smoke [--execution-env MONAD_TEN]\n";
    }

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

        auto const code_hash = std::bit_cast<monad::bytes32_t>(
            ethash::keccak256(bytecode.data(), bytecode.size()));
        auto const varcode = vm.try_insert_varcode_raw(code_hash, code);
        auto runtime_context = monad::vm::runtime::Context::from(
            &host.get_interface(), host.to_context(), &message, code);

        auto const result = vm.execute_raw<monad::MonadTraits<MONAD_TEN>>(
            runtime_context, code_hash, varcode);

        bool const valid_output =
            result.output_size == 32 && result.output_data != nullptr &&
            std::all_of(
                result.output_data,
                result.output_data + 31,
                [](std::uint8_t const byte) { return byte == 0; }) &&
            result.output_data[31] == 0x2a;

        if (result.status_code != EVMC_SUCCESS || !valid_output) {
            std::cerr << "MONAD_TEN smoke execution failed"
                      << "\nstatus=" << result.status_code << "\noutput="
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
    if (argc == 1 || std::string_view{argv[1]} == "--help" ||
        std::string_view{argv[1]} == "-h") {
        print_usage(std::cout);
        return 0;
    }

    if (std::string_view{argv[1]} == "--version") {
        std::cout << MONAD_EXECBENCH_VERSION << " (Monad "
                  << MONAD_EXECBENCH_MONAD_COMMIT << ")\n";
        return 0;
    }

    if (std::string_view{argv[1]} != "smoke") {
        std::cerr << "unknown command: " << argv[1] << '\n';
        print_usage(std::cerr);
        return 2;
    }

    std::string_view execution_env{"MONAD_TEN"};
    for (int i = 2; i < argc; ++i) {
        std::string_view const argument{argv[i]};
        if (argument == "--help" || argument == "-h") {
            print_usage(std::cout);
            return 0;
        }
        if (argument != "--execution-env" || i + 1 >= argc) {
            std::cerr << "invalid smoke argument: " << argument << '\n';
            print_usage(std::cerr);
            return 2;
        }
        execution_env = argv[++i];
    }

    if (execution_env != "MONAD_TEN") {
        std::cerr << "unsupported execution environment: " << execution_env
                  << '\n';
        return 2;
    }

    return run_monad_ten_smoke();
}
