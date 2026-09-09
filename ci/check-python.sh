#!/usr/bin/env bash
set -euo pipefail

python -m ruff check capture analysis tests scripts
python -m ruff format --check capture analysis tests scripts
python -m unittest discover -s tests/capture -v
python -m unittest discover -s tests/report -v
python -m unittest discover -s tests/release -v
python scripts/check_release.py
