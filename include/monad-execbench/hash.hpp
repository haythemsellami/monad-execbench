#pragma once

#include <filesystem>
#include <string>
#include <string_view>

namespace monad_execbench
{
    std::string sha256_hex(std::string_view value);
    std::string sha256_file(std::filesystem::path const &path);
}
