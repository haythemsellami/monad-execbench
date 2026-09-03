#pragma once

#include <monad-execbench/fixture.hpp>

#include <iosfwd>
#include <optional>
#include <string>

namespace monad_execbench
{
    struct VerificationSummary
    {
        std::size_t cases{};
    };

    VerificationSummary verify_fixture_suite(
        FixtureSuite const &suite,
        std::optional<std::string> const &execution_env, std::ostream &output);
}
