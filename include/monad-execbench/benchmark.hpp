#pragma once

#include <iosfwd>

namespace monad_execbench
{
    void print_benchmark_usage(std::ostream &output);
    int run_benchmark_command(int argc, char **argv);
}
