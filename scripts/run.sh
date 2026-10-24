#!/usr/bin/env bash
# Download Home Assistant Core requirements for HA_CORE_REF and run the checker.
# HA_CORE_REF=latest-release resolves to the tag of the latest published Core release.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
core_ref="${HA_CORE_REF:?HA_CORE_REF is required}"

if [[ "$core_ref" == "latest-release" ]]; then
  auth=()
  if [[ -n "${GH_TOKEN:-}" ]]; then
    auth=(--header "Authorization: Bearer ${GH_TOKEN}")
  fi
  core_ref="$(
    curl --fail --silent --show-error --location "${auth[@]}" \
      --header "Accept: application/vnd.github+json" \
      "https://api.github.com/repos/home-assistant/core/releases/latest" \
      | python -c 'import json, sys; print(json.load(sys.stdin)["tag_name"])'
  )"
  echo "Latest Home Assistant Core release: ${core_ref}"
fi

core_dir="${RUNNER_TEMP:-$(mktemp -d)}/ha-core-dependencies-${core_ref}"
mkdir -p "$core_dir"
base_url="https://raw.githubusercontent.com/home-assistant/core/${core_ref}"

# requirements_all.txt includes requirements.txt via -r
for file in requirements_all.txt requirements.txt; do
  curl --fail --silent --show-error --location \
    "$base_url/$file" --output "$core_dir/$file"
done

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  echo "core-ref=${core_ref}" >> "$GITHUB_OUTPUT"
fi

python "$script_dir/check_dependencies.py" \
  --pyproject "${PYPROJECT:-pyproject.toml}" \
  --setup-cfg "${SETUP_CFG:-setup.cfg}" \
  --setup-py "${SETUP_PY:-setup.py}" \
  --library-requirements "${LIBRARY_REQUIREMENTS:-requirements.txt}" \
  --core-requirements "$core_dir/requirements_all.txt" \
  --core-ref "$core_ref" \
  --missing-policy "${MISSING_POLICY:-warn}"
