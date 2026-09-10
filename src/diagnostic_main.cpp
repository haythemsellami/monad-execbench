#include <monad-execbench/diagnostics.hpp>
#include <monad-execbench/hash.hpp>
#include <monad-execbench/replay.hpp>

#include <iostream>
#include <string_view>

int main(int argc, char **argv)
{
    if (argc == 2 && std::string_view{argv[1]} == "--version") {
        std::cout << "monad-execbench-diagnostics " << MONAD_EXECBENCH_VERSION
                  << '\n';
        return 0;
    }
    if (argc == 2 && std::string_view{argv[1]} == "--help") {
        std::cout << "Usage: monad-execbench-diagnostics <fixture-suite>\n"
                     "Writes verified interpreter diagnostics JSON to stdout; "
                     "no timing modes.\n";
        return 0;
    }
    if (argc != 2 || std::string_view{argv[1]}.starts_with('-')) {
        std::cerr << "Usage: monad-execbench-diagnostics <fixture-suite>\n";
        return 2;
    }
    try {
        auto const suite = monad_execbench::load_fixture_suite(argv[1]);
        monad_execbench::verify_fixture_suite(suite, std::nullopt, std::cerr);
        auto diagnostics = monad_execbench::diagnose_fixture_suite(suite);
        diagnostics["runner_sha256"] =
            monad_execbench::sha256_file("/proc/self/exe");
        diagnostics["build_type"] = MONAD_EXECBENCH_BUILD_TYPE;
        diagnostics["compiler"] = std::string{MONAD_EXECBENCH_CXX_COMPILER_ID} +
                                  " " + MONAD_EXECBENCH_CXX_COMPILER_VERSION;
        std::cout << diagnostics.dump(2) << '\n';
        return 0;
    } catch (std::exception const &error) {
        std::cerr << "diagnostics failed: " << error.what() << '\n';
        return 1;
    }
}
