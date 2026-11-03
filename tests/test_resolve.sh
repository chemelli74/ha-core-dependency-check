#!/usr/bin/env bash
# Resolve fixtures against a local wheel index and compare exit codes.
set -uo pipefail

tests_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="$tests_dir/../scripts/resolve_dependencies.py"
core_dir="$tests_dir/fixtures/resolve/core"
wheels="$(mktemp -d)"
trap 'rm -rf "$wheels"' EXIT
status=0

# liba 2.0 needs a newer libb than the libb==2.0 Core pins; liba 1.0 does not.
# libc needs a Python patch release, which Core's requires-python satisfies.
# libd, required by Core, caps libe below 2.
# Core pins self-pin-library 1.0, which caps libf below 2; release 2.0 needs libf 2.
python - "$wheels" <<'PYEOF'
import sys
import zipfile
from pathlib import Path

packages = {
    ("liba", "1.0"): ["libb>=1"],
    ("liba", "2.0"): ["libb>=3"],
    ("libb", "2.0"): [],
    ("libb", "3.0"): [],
    ("libc", "1.0"): [],
    ("libd", "1.0"): ["libe<2"],
    ("libe", "1.0"): [],
    ("libe", "2.0"): [],
    ("libf", "1.0"): [],
    ("libf", "2.0"): [],
    ("self-pin-library", "1.0"): ["libf<2"],
}
requires_python = {"libc": ">=3.14.1"}
for (name, version), requires in packages.items():
    stem = f"{name.replace('-', '_')}-{version}"
    dist_info = f"{stem}.dist-info"
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
    if name in requires_python:
        metadata += f"Requires-Python: {requires_python[name]}\n"
    metadata += "".join(f"Requires-Dist: {requirement}\n" for requirement in requires)
    wheel = "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    with zipfile.ZipFile(Path(sys.argv[1]) / f"{stem}-py3-none-any.whl", "w") as archive:
        archive.writestr(f"{dist_info}/METADATA", metadata)
        archive.writestr(f"{dist_info}/WHEEL", wheel)
        archive.writestr(f"{dist_info}/RECORD", "")
PYEOF

# A uv that never finishes, to exercise the resolver timeout
mkdir "$wheels/stalled-uv"
printf '#!/bin/sh\nexec sleep 30\n' > "$wheels/stalled-uv/uv"
chmod +x "$wheels/stalled-uv/uv"

expect() {
  local name="$1" fixture="$2" expected="$3" expected_output="$4"
  local core="${CORE_DIR:-$core_dir}"
  shift 4
  (cd "$tests_dir/fixtures/resolve/$fixture" && python "$script" \
    --core-requirements "$core/requirements_all.txt" \
    --core-constraints "$core/package_constraints.txt" \
    --core-pyproject "$core/pyproject.toml" \
    --find-links "$wheels" "$@") > "$wheels/output" 2>&1
  local actual=$?
  if [[ "$actual" == "$expected" ]] && grep -qF -- "$expected_output" "$wheels/output"; then
    echo "ok   $name (exit $actual)"
  else
    echo "FAIL $name: expected exit $expected and output '$expected_output', got exit $actual"
    cat "$wheels/output"
    status=1
  fi
}

expect indirect-ok indirect-ok 0 "check PASSED"
expect indirect-conflict indirect-conflict 1 "check FAILED"
expect python-patch python-patch 0 "check PASSED"
expect transitive-conflict transitive-conflict 1 "versions of libd depend on libe<2"
expect self-pin self-pin 0 "Library: Self_Pin.Library (Core's own pin of it is left out)"
expect self-pin-setup-py self-pin-setup-py 0 "Library: self-pin-library (Core's own pin of it is left out)"
expect self-pin-setup-py-second-call self-pin-setup-py-second-call 1 "WARNING: library name not found"
CORE_DIR="$tests_dir/fixtures/resolve/core-conflict" \
  expect core-conflict indirect-ok 0 "cannot be resolved even without the library"
PATH="$wheels/stalled-uv:$PATH" expect timeout indirect-ok 0 "timed out after 1s" --timeout 1

exit $status
