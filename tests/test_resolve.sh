#!/usr/bin/env bash
# Resolve fixtures against a local wheel index and compare exit codes.
set -uo pipefail

tests_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="$tests_dir/../scripts/resolve_dependencies.py"
core_dir="$tests_dir/fixtures/resolve/core"
wheels="$(mktemp -d)"
trap 'rm -rf "$wheels"' EXIT
status=0

# liba 2.0 needs a newer libb than the libb==2.0 Core pins; liba 1.0 does not
python - "$wheels" <<'PYEOF'
import sys
import zipfile
from pathlib import Path

packages = {
    ("liba", "1.0"): ["libb>=1"],
    ("liba", "2.0"): ["libb>=3"],
    ("libb", "2.0"): [],
    ("libb", "3.0"): [],
}
for (name, version), requires in packages.items():
    dist_info = f"{name}-{version}.dist-info"
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
    metadata += "".join(f"Requires-Dist: {requirement}\n" for requirement in requires)
    wheel = "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    with zipfile.ZipFile(Path(sys.argv[1]) / f"{name}-{version}-py3-none-any.whl", "w") as archive:
        archive.writestr(f"{dist_info}/METADATA", metadata)
        archive.writestr(f"{dist_info}/WHEEL", wheel)
        archive.writestr(f"{dist_info}/RECORD", "")
PYEOF

expect() {
  local fixture="$1" expected="$2"
  (cd "$tests_dir/fixtures/resolve/$fixture" && python "$script" \
    --core-requirements "$core_dir/requirements_all.txt" \
    --core-requirements "$core_dir/package_constraints.txt" \
    --core-pyproject "$core_dir/pyproject.toml" \
    --find-links "$wheels") > "$wheels/output" 2>&1
  local actual=$?
  if [[ "$actual" == "$expected" ]]; then
    echo "ok   $fixture (exit $actual)"
  else
    echo "FAIL $fixture: expected exit $expected, got $actual"
    cat "$wheels/output"
    status=1
  fi
}

expect indirect-ok 0
expect indirect-conflict 1

exit $status
