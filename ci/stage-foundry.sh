#!/usr/bin/env bash
set -euo pipefail

# Foundry installers may put symlinks in bin/ whose targets live elsewhere.
# Stage the actual executables so the read-only container mount is self-contained.
mkdir -p results/ci/foundry-bin
for tool in forge anvil; do
  cp -L "$(command -v "$tool")" "results/ci/foundry-bin/$tool"
done
