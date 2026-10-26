#!/usr/bin/env python3
"""Report whether a pull request changes the library's declared dependencies."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from check_dependencies import read_library


def normalized(requirements: list[Requirement]) -> set[str]:
    """Return requirements as comparable strings, ignoring name spelling and order."""
    result = set()
    for requirement in requirements:
        extras = f"[{','.join(sorted(requirement.extras))}]" if requirement.extras else ""
        marker = f"; {requirement.marker}" if requirement.marker else ""
        result.add(
            f"{canonicalize_name(requirement.name)}{extras}{requirement.specifier}{marker}"
        )
    return result


def main() -> int:
    """Compare the dependencies in the working tree with those in --base-dir."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--setup-cfg", type=Path, default=Path("setup.cfg"))
    parser.add_argument("--setup-py", type=Path, default=Path("setup.py"))
    parser.add_argument("--library-requirements", type=Path, default=Path("requirements.txt"))
    args = parser.parse_args()

    paths = (args.pyproject, args.setup_cfg, args.setup_py, args.library_requirements)
    # Unreadable declarations count as a change, so the check runs and reports them
    try:
        head = normalized(read_library(*paths))
        base = normalized(read_library(*(args.base_dir / path for path in paths)))
    except ValueError as err:
        print(f"Cannot compare dependencies ({err}); treating them as changed")
        changed = True
    else:
        for line in sorted(base - head):
            print(f"removed: {line}")
        for line in sorted(head - base):
            print(f"added: {line}")
        changed = head != base
        print("Dependencies changed" if changed else "Dependencies unchanged")

    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as file:
            file.write(f"changed={'true' if changed else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
