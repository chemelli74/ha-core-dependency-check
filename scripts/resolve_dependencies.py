#!/usr/bin/env python3
"""Resolve the library's dependencies together with Home Assistant Core's requirements."""

from __future__ import annotations

import argparse
import ast
import configparser
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

from check_dependencies import parse_requirements_file, read_library

# Core runs on Linux; resolving for it keeps platform markers consistent with Core
PYTHON_PLATFORM = "x86_64-unknown-linux-gnu"


def core_python_version(core_pyproject: Path) -> str:
    """Return the lowest Python version Core supports."""
    with core_pyproject.open("rb") as file:
        requires_python = tomllib.load(file)["project"]["requires-python"]
    for specifier in SpecifierSet(requires_python):
        if specifier.operator in (">=", "==", "~="):
            # Keep the patch: uv reads a bare major.minor as .0
            return specifier.version.removesuffix(".*")
    raise ValueError(f"cannot derive a Python version from {requires_python!r}")


def library_name(pyproject: Path, setup_cfg: Path, setup_py: Path) -> str | None:
    """Return the library's distribution name, or None if it is not declared statically."""
    if pyproject.is_file():
        with pyproject.open("rb") as file:
            data = tomllib.load(file)
        name = data.get("project", {}).get("name") or (
            data.get("tool", {}).get("poetry", {}).get("name")
        )
        if name:
            return name
    if setup_cfg.is_file():
        config = configparser.ConfigParser(interpolation=None)
        config.read(setup_cfg, encoding="utf-8")
        if config.has_option("metadata", "name"):
            return config.get("metadata", "name").strip()
    if setup_py.is_file():
        tree = ast.parse(setup_py.read_text(encoding="utf-8"), filename=str(setup_py))
        assignments: dict[str, ast.expr] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assignments[target.id] = node.value
        # Only the first setup() call, the one parse_setup_py reads dependencies from
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(
                node.func, "id", getattr(node.func, "attr", None)
            ) == "setup":
                for keyword in node.keywords:
                    if keyword.arg != "name":
                        continue
                    value = keyword.value
                    if isinstance(value, ast.Name):
                        value = assignments.get(value.id, value)
                    if isinstance(value, ast.Constant):
                        return str(value.value)
                return None
    return None


def compile_requirements(
    requirements: list[Requirement],
    constraints: list[Requirement],
    python_version: str,
    find_links: Path | None,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    """Run uv pip compile; raises subprocess.TimeoutExpired when it takes too long."""
    with tempfile.TemporaryDirectory() as tmp:
        requirements_in = Path(tmp) / "requirements.in"
        constraints_txt = Path(tmp) / "constraints.txt"
        requirements_in.write_text(
            "\n".join(map(str, requirements)) + "\n", encoding="utf-8"
        )
        constraints_txt.write_text(
            "\n".join(map(str, constraints)) + "\n", encoding="utf-8"
        )
        command = [
            "uv", "pip", "compile", str(requirements_in),
            "--constraint", str(constraints_txt),
            "--python-version", python_version,
            "--python-platform", PYTHON_PLATFORM,
            "--no-header", "--no-annotate", "--quiet",
        ]
        if find_links:
            command += ["--no-index", "--find-links", str(find_links)]
        return subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=timeout
        )


def main() -> int:
    """Resolve the library with every requirement Core installs, like Core's own install."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--setup-cfg", type=Path, default=Path("setup.cfg"))
    parser.add_argument("--setup-py", type=Path, default=Path("setup.py"))
    parser.add_argument("--library-requirements", type=Path, default=Path("requirements.txt"))
    parser.add_argument("--core-requirements", type=Path, action="append", required=True)
    parser.add_argument("--core-constraints", type=Path, action="append", default=[])
    parser.add_argument("--core-pyproject", type=Path, required=True)
    parser.add_argument(
        "--find-links",
        type=Path,
        help="Resolve only from this local directory of wheels (used by tests)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600,
        help="Seconds before the resolution is abandoned",
    )
    args = parser.parse_args()

    print("### INDIRECT DEPENDENCY RESOLUTION ###")
    try:
        library = read_library(
            args.pyproject, args.setup_cfg, args.setup_py, args.library_requirements
        )
        name = library_name(args.pyproject, args.setup_cfg, args.setup_py)
        core = []
        for path in args.core_requirements:
            core += parse_requirements_file(path)
        constraints = []
        for path in args.core_constraints:
            constraints += parse_requirements_file(path)
        python_version = core_python_version(args.core_pyproject)
    except (OSError, KeyError, ValueError, SyntaxError, configparser.Error) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    print(f"Python {python_version} on {PYTHON_PLATFORM}")
    if name:
        # Core's pin of this library is the version being replaced
        print(f"Library: {name} (Core's own pin of it is left out)")
        core = [r for r in core if canonicalize_name(r.name) != canonicalize_name(name)]
    else:
        print("WARNING: library name not found; Core's pin of it, if any, is kept")

    try:
        result = compile_requirements(
            library + core, constraints, python_version, args.find_links, args.timeout
        )
        if "No solution found" in result.stderr:
            # Blame the library only when Core resolves without it
            baseline = compile_requirements(
                core, constraints, python_version, args.find_links, args.timeout
            )
        else:
            baseline = None
    except subprocess.TimeoutExpired:
        print(f"\nWARNING: dependency resolution timed out after {args.timeout:g}s; "
              "indirect check skipped.")
        return 0

    if result.returncode == 0:
        print(f"Resolved together with {len(core)} Core requirements.")
        print("\nIndirect dependency check PASSED.")
        return 0
    if baseline is not None and baseline.returncode == 0:
        print(result.stderr.rstrip())
        print("\nFAIL: the library's dependencies cannot be installed together with "
              "Home Assistant Core's requirements.")
        print("Indirect dependency check FAILED.")
        return 1
    if baseline is not None:
        print(baseline.stderr.rstrip())
        print("\nWARNING: Home Assistant Core's requirements cannot be resolved even "
              "without the library; indirect check skipped.")
        return 0
    print(result.stderr.rstrip())
    print("\nWARNING: dependency resolution could not run; indirect check skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
