#!/usr/bin/env bash
set -euo pipefail
mvt_checkout="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3.12 -m venv "$mvt_checkout/.venv"
"$mvt_checkout/.venv/bin/python" -m pip install -e "$mvt_checkout[dev]"
"$mvt_checkout/.venv/bin/mvt" doctor
