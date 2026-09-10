#pragma once

#include <category/vm/interpreter/intercode.hpp>
#include <category/vm/runtime/types.hpp>
#include <monad-execbench/diagnostic_hooks.hpp>
#include <monad-execbench/fixture.hpp>
#include <nlohmann/json.hpp>

namespace monad_execbench
{
    void diagnostic_begin();
    nlohmann::json diagnostic_finish(std::uint64_t verified_gas);
    nlohmann::json diagnose_fixture_suite(FixtureSuite const &suite);
} // namespace monad_execbench
