#!/usr/bin/env python3
"""Pick the Home Assistant Core ref to check from the pull request labels."""

from __future__ import annotations

import json
import os
import sys

DEV_LABEL = "core-beta-release"
RELEASE_LABEL = "core-patch-release"


def main() -> int:
    """Write core-ref (or skip) to GITHUB_OUTPUT based on PR labels."""
    event_name = os.environ.get("EVENT_NAME", "")
    # Labels come from the environment, never interpolated into the shell
    labels = set(json.loads(os.environ.get("LABELS") or "null") or [])

    if event_name == "pull_request_target":
        # The default checkout is the base branch, so the PR's dependencies are never read
        print(
            "::error::Run this action on 'pull_request', not 'pull_request_target': "
            "pull_request_target checks out the base branch instead of the pull request"
        )
        return 1
    if event_name != "pull_request":
        print(f"::notice::Not a pull request ({event_name}); dependency check skipped")
        result = {"skip": "true", "core-ref": ""}
    elif os.environ.get("DEPS_CHANGED") == "false":
        print("::notice::Dependencies unchanged; dependency check skipped")
        result = {"skip": "true", "core-ref": ""}
    else:
        selected = [
            ref
            for label, ref in ((DEV_LABEL, "dev"), (RELEASE_LABEL, "latest-release"))
            if label in labels
        ]
        if len(selected) != 1:
            state = "both labels are set" if selected else "no label is set"
            print(
                f"::error::Label missing: add exactly one of '{DEV_LABEL}' "
                f"(check against Core dev) or '{RELEASE_LABEL}' "
                f"(check against the latest Core release); {state}"
            )
            return 1
        print(f"Selected Core ref: {selected[0]}")
        result = {"skip": "false", "core-ref": selected[0]}

    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as file:
            for key, value in result.items():
                file.write(f"{key}={value}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
