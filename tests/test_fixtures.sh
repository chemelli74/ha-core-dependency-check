#!/usr/bin/env bash
# Run the checker offline against each fixture and compare exit codes.
set -uo pipefail

tests_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
checker="$tests_dir/../scripts/check_dependencies.py"
core="$tests_dir/fixtures/core/requirements_all.txt"
status=0

expect() {
  local fixture="$1" expected="$2"
  (cd "$tests_dir/fixtures/$fixture" && python "$checker" --core-requirements "$core" --core-ref fixture) > "$tests_dir/../.test-output" 2>&1
  local actual=$?
  if [[ "$actual" == "$expected" ]]; then
    echo "ok   $fixture (exit $actual)"
  else
    echo "FAIL $fixture: expected exit $expected, got $actual"
    cat "$tests_dir/../.test-output"
    status=1
  fi
}

for fixture in pep621 pep621-dynamic poetry setup-cfg setup-py requirements-only; do
  expect "$fixture" 0
done
expect incompatible 1

rm -f "$tests_dir/../.test-output"
exit $status
