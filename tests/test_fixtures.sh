#!/usr/bin/env bash
# Run the checker offline against each fixture and compare exit codes.
set -uo pipefail

tests_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
checker="$tests_dir/../scripts/check_dependencies.py"
core_dir="$tests_dir/fixtures/core"
pypi_url="file://$tests_dir/fixtures/pypi"
status=0

expect() {
  local fixture="$1" expected="$2"
  (cd "$tests_dir/fixtures/$fixture" && python "$checker" \
    --core-requirements "$core_dir/requirements_all.txt" \
    --core-requirements "$core_dir/package_constraints.txt" \
    --pypi-url "$pypi_url" --core-ref fixture) > "$tests_dir/../.test-output" 2>&1
  local actual=$?
  if [[ "$actual" == "$expected" ]]; then
    echo "ok   $fixture (exit $actual)"
  else
    echo "FAIL $fixture: expected exit $expected, got $actual"
    cat "$tests_dir/../.test-output"
    status=1
  fi
}

for fixture in pep621 pep621-dynamic poetry setup-cfg setup-py requirements-only \
  constraints-pin constraints-range; do
  expect "$fixture" 0
done
for fixture in incompatible constraints-pin-incompatible constraints-range-incompatible; do
  expect "$fixture" 1
done

rm -f "$tests_dir/../.test-output"
exit $status
