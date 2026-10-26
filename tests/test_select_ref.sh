#!/usr/bin/env bash
# Run the label selection with several label sets and compare the outcome.
set -uo pipefail

tests_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
selector="$tests_dir/../scripts/select_ref.py"
status=0

expect() {
  local name="$1" event="$2" labels="$3" expected_exit="$4" expected_output="$5"
  local deps_changed="${6:-}"
  local output_file
  output_file="$(mktemp)"
  EVENT_NAME="$event" LABELS="$labels" DEPS_CHANGED="$deps_changed" GITHUB_OUTPUT="$output_file" \
    python "$selector" > /dev/null
  local actual_exit=$?
  local actual_output
  actual_output="$(tr '\n' ' ' < "$output_file")"
  rm -f "$output_file"
  if [[ "$actual_exit" == "$expected_exit" && "$actual_output" == "$expected_output" ]]; then
    echo "ok   $name"
  else
    echo "FAIL $name: expected exit $expected_exit '$expected_output', got exit $actual_exit '$actual_output'"
    status=1
  fi
}

expect dev-label pull_request '["core-beta-release", "bug"]' 0 "skip=false core-ref=dev "
expect release-label pull_request '["core-patch-release"]' 0 "skip=false core-ref=latest-release "
expect both-labels pull_request '["core-beta-release", "core-patch-release"]' 1 ""
expect no-label pull_request '["bug"]' 1 ""
expect empty-labels pull_request '[]' 1 ""
expect push push 'null' 0 "skip=true core-ref= "
expect deps-unchanged-no-label pull_request '[]' 0 "skip=true core-ref= " false
expect deps-unchanged-both-labels pull_request '["core-beta-release", "core-patch-release"]' 0 "skip=true core-ref= " false
expect deps-changed-no-label pull_request '[]' 1 "" true
expect deps-changed-release-label pull_request '["core-patch-release"]' 0 "skip=false core-ref=latest-release " true

exit $status
