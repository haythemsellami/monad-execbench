#pragma once

#include <monad-execbench/fixture.hpp>

#include <cstddef>
#include <cstdint>
#include <iosfwd>
#include <memory>
#include <optional>
#include <string>
#include <string_view>

namespace monad_execbench
{
    struct VerificationSummary
    {
        std::size_t cases{};
    };

    enum class BenchmarkMode
    {
        dual_hot,
        interpreter_hot,
    };

    std::string_view benchmark_mode_name(BenchmarkMode mode);

    struct BenchmarkSample
    {
        std::uint64_t gas_used{};
        std::size_t output_size{};
        std::size_t log_count{};
    };

    class BenchmarkIteration
    {
    public:
        ~BenchmarkIteration();

        BenchmarkIteration(BenchmarkIteration const &) = delete;
        BenchmarkIteration &operator=(BenchmarkIteration const &) = delete;
        BenchmarkIteration(BenchmarkIteration &&) noexcept;
        BenchmarkIteration &operator=(BenchmarkIteration &&) noexcept;

        void execute();
        BenchmarkSample validate();

    private:
        struct Impl;
        std::unique_ptr<Impl> impl_;

        explicit BenchmarkIteration(std::unique_ptr<Impl> impl);
        friend class BenchmarkSession;
    };

    class BenchmarkSession
    {
    public:
        BenchmarkSession(FixtureSuite const &suite, BenchmarkMode mode);
        ~BenchmarkSession();

        BenchmarkSession(BenchmarkSession const &) = delete;
        BenchmarkSession &operator=(BenchmarkSession const &) = delete;
        BenchmarkSession(BenchmarkSession &&) noexcept;
        BenchmarkSession &operator=(BenchmarkSession &&) noexcept;

        BenchmarkIteration prepare(ReplayCase const &replay_case);

    private:
        struct Impl;
        std::unique_ptr<Impl> impl_;
    };

    VerificationSummary verify_fixture_suite(
        FixtureSuite const &suite,
        std::optional<std::string> const &execution_env, std::ostream &output);
}
