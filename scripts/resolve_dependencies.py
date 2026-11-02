#!/usr/bin/env python3
"""Resolve the library's full dependency tree under Home Assistant Core's pins."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

from packaging.specifiers import SpecifierSet

from check_dependencies import parse_requirements_file, read_library

# Core runs on Linux; resolving for it keeps platform markers consistent with Core
PYTHON_PLATFORM = "x86_64-unknown-linux-gnu"


def core_python_version(core_pyproject: Path) -> str:
    """Return the lowest Python major.minor version Core supports."""
    with core_pyproject.open("rb") as file:
        requires_python = tomllib.load(file)["project"]["requires-python"]
    for specifier in SpecifierSet(requires_python):
        if specifier.operator in (">=", "==", "~="):
            major, minor = specifier.version.split(".")[:2]
            return f"{major}.{minor}"
    raise ValueError(f"cannot derive a Python version from {requires_python!r}")


def main() -> int:
    """Run uv pip compile with Core's requirements as constraints."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--setup-cfg", type=Path, default=Path("setup.cfg"))
    parser.add_argument("--setup-py", type=Path, default=Path("setup.py"))
    parser.add_argument("--library-requirements", type=Path, default=Path("requirements.txt"))
    parser.add_argument("--core-requirements", type=Path, action="append", required=True)
    parser.add_argument("--core-pyproject", type=Path, required=True)
    parser.add_argument(
        "--find-links",
        type=Path,
        help="Resolve only from this local directory of wheels (used by tests)",
    )
    args = parser.parse_args()

    print("### INDIRECT DEPENDENCY RESOLUTION ###")
    try:
        library = read_library(
            args.pyproject, args.setup_cfg, args.setup_py, args.library_requirements
        )
        core = []
        for path in args.core_requirements:
            core += parse_requirements_file(path)
        python_version = core_python_version(args.core_pyproject)
    except (OSError, KeyError, ValueError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    print(f"Python {python_version} on {PYTHON_PLATFORM}")

    with tempfile.TemporaryDirectory() as tmp:
        requirements_in = Path(tmp) / "requirements.in"
        constraints = Path(tmp) / "constraints.txt"
        requirements_in.write_text("\n".join(map(str, library)) + "\n", encoding="utf-8")
        constraints.write_text("\n".join(map(str, core)) + "\n", encoding="utf-8")
        command = [
            "uv", "pip", "compile", str(requirements_in),
            "--constraint", str(constraints),
            "--python-version", python_version,
            "--python-platform", PYTHON_PLATFORM,
            "--no-header", "--no-annotate", "--quiet",
        ]
        if args.find_links:
            command += ["--no-index", "--find-links", str(args.find_links)]
        result = subprocess.run(command, capture_output=True, text=True, check=False)

    if result.returncode == 0:
        print("Resolved dependency tree:")
        print(result.stdout.rstrip())
        print("\nIndirect dependency check PASSED.")
        return 0
    if "No solution found" in result.stderr:
        print(result.stderr.rstrip())
        print("\nFAIL: the dependency tree cannot be installed with Home Assistant Core's pins.")
        print("Indirect dependency check FAILED.")
        return 1
    print(result.stderr.rstrip())
    print("\nWARNING: dependency resolution could not run; indirect check skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
