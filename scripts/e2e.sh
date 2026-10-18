#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
case_dir="$repo_dir/examples/fixture-stage"
mvt_bin="$repo_dir/.venv/bin/mvt"
"$mvt_bin" contract validate "$case_dir"
"$mvt_bin" build "$case_dir"
"$mvt_bin" render "$case_dir" --set proofs
"$mvt_bin" audit "$case_dir"
"$mvt_bin" animate build "$case_dir" --sequence shuttle
"$mvt_bin" shield "$case_dir"
"$mvt_bin" handoff "$case_dir"
