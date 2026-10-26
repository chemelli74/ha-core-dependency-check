#!/usr/bin/env bash
# Compare base and head fixtures and check whether a dependency change is reported.
set -uo pipefail

tests_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="$tests_dir/../scripts/deps_changed.py"
status=0

expect() {
  local fixture="$1" expected="$2"
  local output_file
  output_file="$(mktemp)"
  (cd "$tests_dir/fixtures/changes/$fixture/head" \
    && GITHUB_OUTPUT="$output_file" python "$script" --base-dir ../base > /dev/null)
  local actual
  actual="$(cat "$output_file")"
  rm -f "$output_file"
  if [[ "$actual" == "changed=$expected" ]]; then
    echo "ok   $fixture (changed=$expected)"
  else
    echo "FAIL $fixture: expected changed=$expected, got '$actual'"
    status=1
  fi
}

expect version-only false
expect spelling-and-order false
expect constraint-changed true
expect dependency-added true

exit $status
