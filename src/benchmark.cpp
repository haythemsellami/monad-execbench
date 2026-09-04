#include <monad-execbench/benchmark.hpp>

#include <monad-execbench/fixture.hpp>
#include <monad-execbench/replay.hpp>

#include <category/core/hex.hpp>

#include <benchmark/benchmark.h>

#include <charconv>
#include <cstdint>
#include <exception>
#include <filesystem>
#include <iostream>
#include <limits>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

namespace monad_execbench
{
    namespace
    {
        struct BenchmarkOptions
        {
            std::filesystem::path fixture_directory;
            std::optional<std::string> execution_env;
            BenchmarkMode mode{BenchmarkMode::dual_hot};
            int repetitions{50};
            std::string filter{"*"};
            std::filesystem::path output;
            std::vector<std::string> passthrough;
        };

        std::string required_value(
            int argc, char **argv, int &index, std::string_view const option)
        {
            if (index + 1 >= argc) {
                throw std::invalid_argument{
                    std::string{option} + " requires a value"};
            }
            return argv[++index];
        }

        int repetitions(std::string const &text)
        {
            int result{};
            auto const parsed = std::from_chars(
                text.data(), text.data() + text.size(), result, 10);
            if (parsed.ec != std::errc{} ||
                parsed.ptr != text.data() + text.size() || result <= 0) {
                throw std::invalid_argument{
                    "--repetitions must be a positive integer"};
            }
            return result;
        }

        BenchmarkMode mode(std::string const &value)
        {
            if (value == "dual-hot") {
                return BenchmarkMode::dual_hot;
            }
            if (value == "interpreter-hot") {
                return BenchmarkMode::interpreter_hot;
            }
            throw std::invalid_argument{"unsupported benchmark mode: " + value};
        }

        bool owned_benchmark_option(std::string_view const argument)
        {
            constexpr std::string_view owned[] = {
                "--benchmark_out",
                "--benchmark_out_format",
                "--benchmark_repetitions",
                "--benchmark_filter",
                "--benchmark_enable_random_interleaving",
            };
            for (auto const option : owned) {
                if (argument == option || (argument.starts_with(option) &&
                                           argument.size() > option.size() &&
                                           argument[option.size()] == '=')) {
                    return true;
                }
            }
            return false;
        }

        BenchmarkOptions parse_options(int argc, char **argv)
        {
            if (argc < 3) {
                throw std::invalid_argument{
                    "run requires a fixture-suite directory"};
            }

            BenchmarkOptions options{.fixture_directory = argv[2]};
            for (int i = 3; i < argc; ++i) {
                std::string_view const argument{argv[i]};
                if (argument == "--") {
                    for (++i; i < argc; ++i) {
                        std::string passthrough{argv[i]};
                        if (owned_benchmark_option(passthrough)) {
                            throw std::invalid_argument{
                                "Google Benchmark option is controlled by "
                                "monad-execbench: " +
                                passthrough};
                        }
                        options.passthrough.push_back(std::move(passthrough));
                    }
                    break;
                }
                if (argument == "--execution-env") {
                    options.execution_env =
                        required_value(argc, argv, i, argument);
                }
                else if (argument == "--mode") {
                    options.mode =
                        mode(required_value(argc, argv, i, argument));
                }
                else if (argument == "--repetitions") {
                    options.repetitions =
                        repetitions(required_value(argc, argv, i, argument));
                }
                else if (argument == "--filter") {
                    options.filter = required_value(argc, argv, i, argument);
                }
                else if (argument == "--output") {
                    options.output = required_value(argc, argv, i, argument);
                }
                else {
                    throw std::invalid_argument{
                        "invalid run argument: " + std::string{argument}};
                }
            }

            if (options.filter.empty()) {
                throw std::invalid_argument{"--filter must not be empty"};
            }
            if (options.output.empty()) {
                throw std::invalid_argument{"run requires --output <path>"};
            }
            return options;
        }

        bool
        glob_match(std::string_view const pattern, std::string_view const value)
        {
            std::size_t pattern_index{};
            std::size_t value_index{};
            std::size_t star = std::string_view::npos;
            std::size_t retry_value{};

            while (value_index < value.size()) {
                if (pattern_index < pattern.size() &&
                    (pattern[pattern_index] == '?' ||
                     pattern[pattern_index] == value[value_index])) {
                    ++pattern_index;
                    ++value_index;
                }
                else if (
                    pattern_index < pattern.size() &&
                    pattern[pattern_index] == '*') {
                    star = pattern_index++;
                    retry_value = value_index;
                }
                else if (star != std::string_view::npos) {
                    pattern_index = star + 1;
                    value_index = ++retry_value;
                }
                else {
                    return false;
                }
            }
            while (pattern_index < pattern.size() &&
                   pattern[pattern_index] == '*') {
                ++pattern_index;
            }
            return pattern_index == pattern.size();
        }

        std::filesystem::path
        prepare_output_path(std::filesystem::path const &output)
        {
            auto const absolute =
                std::filesystem::absolute(output).lexically_normal();
            if (std::filesystem::is_directory(absolute)) {
                throw std::invalid_argument{
                    "benchmark output is a directory: " + absolute.string()};
            }
            auto const parent = absolute.parent_path();
            std::error_code error;
            std::filesystem::create_directories(parent, error);
            if (error) {
                throw std::runtime_error{
                    "cannot create benchmark output directory " +
                    parent.string() + ": " + error.message()};
            }
            return absolute;
        }

        std::string block_hash(FixtureSuite const &suite)
        {
            return "0x" + monad::to_hex(suite.block.hash);
        }

        void
        add_context(FixtureSuite const &suite, BenchmarkOptions const &options)
        {
            benchmark::AddCustomContext(
                "monad_execbench_version", MONAD_EXECBENCH_VERSION);
            benchmark::AddCustomContext(
                "monad_execbench_commit", MONAD_EXECBENCH_COMMIT);
            benchmark::AddCustomContext(
                "monad_commit", MONAD_EXECBENCH_MONAD_COMMIT);
            benchmark::AddCustomContext(
                "build_type", MONAD_EXECBENCH_BUILD_TYPE);
            benchmark::AddCustomContext(
                "compiler",
                std::string{MONAD_EXECBENCH_CXX_COMPILER_ID} + " " +
                    MONAD_EXECBENCH_CXX_COMPILER_VERSION);
            benchmark::AddCustomContext("fixture_schema", suite.schema);
            benchmark::AddCustomContext(
                "fixture_directory", suite.directory.string());
            benchmark::AddCustomContext("execution_env", suite.execution_env);
            benchmark::AddCustomContext(
                "block_number", std::to_string(suite.block.number));
            benchmark::AddCustomContext("block_hash", block_hash(suite));
            benchmark::AddCustomContext(
                "benchmark_mode",
                std::string{benchmark_mode_name(options.mode)});
            benchmark::AddCustomContext("case_filter", options.filter);
            benchmark::AddCustomContext(
                "requested_repetitions", std::to_string(options.repetitions));
        }

        void run_case(
            benchmark::State &state, BenchmarkSession &session,
            ReplayCase const &replay_case, std::optional<std::string> &failure)
        {
            if (failure) {
                state.SkipWithError(failure->c_str());
                return;
            }

            BenchmarkSample sample{};
            bool completed = false;
            for (auto _ : state) {
                (void)_;
                bool paused = false;
                try {
                    state.PauseTiming();
                    paused = true;
                    auto iteration = session.prepare(replay_case);
                    state.ResumeTiming();
                    paused = false;
                    try {
                        iteration.execute();
                    }
                    catch (...) {
                        state.PauseTiming();
                        paused = true;
                        throw;
                    }
                    state.PauseTiming();
                    paused = true;
                    sample = iteration.validate();
                    completed = true;
                    state.ResumeTiming();
                    paused = false;
                }
                catch (std::exception const &error) {
                    if (paused) {
                        state.ResumeTiming();
                    }
                    failure =
                        "case '" + replay_case.name + "': " + error.what();
                    state.SkipWithError(failure->c_str());
                    break;
                }
            }

            if (completed) {
                state.counters["execution_gas"] =
                    static_cast<double>(sample.gas_used);
                state.counters["return_data_bytes"] =
                    static_cast<double>(sample.output_size);
                state.counters["log_count"] =
                    static_cast<double>(sample.log_count);
                state.SetLabel(replay_case.expected.status);
            }
        }
    }

    void print_benchmark_usage(std::ostream &output)
    {
        output
            << "  monad-execbench run <fixture-suite> --output <results.json>\n"
            << "      [--execution-env MONAD_TEN]\n"
            << "      [--mode dual-hot|interpreter-hot]\n"
            << "      [--repetitions N] [--filter GLOB]\n"
            << "      [-- <Google Benchmark options>]\n";
    }

    int run_benchmark_command(int argc, char **argv)
    {
        if (argc == 3 && (std::string_view{argv[2]} == "--help" ||
                          std::string_view{argv[2]} == "-h")) {
            print_benchmark_usage(std::cout);
            return 0;
        }

        auto const options = parse_options(argc, argv);
        auto const suite = load_fixture_suite(options.fixture_directory);

        std::vector<ReplayCase const *> selected_cases;
        for (auto const &replay_case : suite.cases) {
            if (glob_match(options.filter, replay_case.name)) {
                selected_cases.push_back(&replay_case);
            }
        }
        if (selected_cases.empty()) {
            throw std::invalid_argument{
                "case filter matched no cases: " + options.filter};
        }

        verify_fixture_suite(suite, options.execution_env, std::cout);
        std::cout << std::flush;
        auto session = std::make_unique<BenchmarkSession>(suite, options.mode);
        auto const output = prepare_output_path(options.output);

        add_context(suite, options);

        std::vector<std::string> benchmark_arguments{
            argv[0],
            "--benchmark_out=" + output.string(),
            "--benchmark_out_format=json",
            "--benchmark_enable_random_interleaving=true"};
        benchmark_arguments.insert(
            benchmark_arguments.end(),
            options.passthrough.begin(),
            options.passthrough.end());
        std::vector<char *> benchmark_argv;
        benchmark_argv.reserve(benchmark_arguments.size());
        for (auto &argument : benchmark_arguments) {
            benchmark_argv.push_back(argument.data());
        }
        auto benchmark_argc = static_cast<int>(benchmark_argv.size());
        benchmark::Initialize(&benchmark_argc, benchmark_argv.data());
        if (benchmark::ReportUnrecognizedArguments(
                benchmark_argc, benchmark_argv.data())) {
            benchmark::Shutdown();
            throw std::invalid_argument{"unrecognized Google Benchmark option"};
        }

        std::optional<std::string> failure;
        auto const mode_name = std::string{benchmark_mode_name(options.mode)};
        for (auto const *replay_case : selected_cases) {
            auto const name = "execute/" + mode_name + "/" + replay_case->name;
            benchmark::RegisterBenchmark(
                name.c_str(),
                [&session, replay_case, &failure](benchmark::State &state) {
                    run_case(state, *session, *replay_case, failure);
                })
                ->Repetitions(options.repetitions)
                ->Unit(benchmark::kNanosecond);
        }

        auto const executed = benchmark::RunSpecifiedBenchmarks();
        benchmark::Shutdown();
        benchmark::ClearRegisteredBenchmarks();

        if (failure) {
            throw std::runtime_error{*failure};
        }
        if (executed == 0) {
            throw std::runtime_error{"Google Benchmark executed no cases"};
        }
        if (!std::filesystem::is_regular_file(output) ||
            std::filesystem::file_size(output) == 0) {
            throw std::runtime_error{
                "Google Benchmark did not write results to " + output.string()};
        }

        std::cout << "results=" << output.string() << '\n';
        return 0;
    }
}
