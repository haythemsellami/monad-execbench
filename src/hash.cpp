#include <monad-execbench/hash.hpp>

#include <silkpre_vendor/sha256.h>

#include <array>
#include <cstdint>
#include <fstream>
#include <stdexcept>

namespace monad_execbench
{
    namespace
    {
        std::string hex_digest(std::array<std::uint8_t, 32> const &digest)
        {
            constexpr char hex[] = "0123456789abcdef";
            std::string result(66, '0');
            result[0] = '0';
            result[1] = 'x';
            for (std::size_t i = 0; i < digest.size(); ++i) {
                result[2 + i * 2] = hex[digest[i] >> 4];
                result[3 + i * 2] = hex[digest[i] & 0x0f];
            }
            return result;
        }
    }

    std::string sha256_hex(std::string_view const value)
    {
        std::array<std::uint8_t, 32> digest{};
        monad_sha256(
            digest.data(),
            reinterpret_cast<std::uint8_t const *>(value.data()),
            value.size(),
            true);
        return hex_digest(digest);
    }

    std::string sha256_file(std::filesystem::path const &path)
    {
        std::ifstream input{path, std::ios::binary | std::ios::ate};
        if (!input) {
            throw std::runtime_error{
                "cannot open file for hashing: " + path.string()};
        }
        auto const end = input.tellg();
        if (end < 0) {
            throw std::runtime_error{
                "cannot inspect file for hashing: " + path.string()};
        }
        std::string payload(static_cast<std::size_t>(end), '\0');
        input.seekg(0);
        if (!payload.empty()) {
            input.read(
                payload.data(), static_cast<std::streamsize>(payload.size()));
        }
        if (input.gcount() != static_cast<std::streamsize>(payload.size()) ||
            input.peek() != std::ifstream::traits_type::eof()) {
            throw std::runtime_error{
                "file changed while hashing: " + path.string()};
        }
        return sha256_hex(payload);
    }
}
