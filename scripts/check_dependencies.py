#!/usr/bin/env python3
"""Compare a library's runtime requirements with Home Assistant Core."""

from __future__ import annotations

import argparse
import ast
import configparser
import json
import re
import sys
import tomllib
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


def parse_requirements_file(path: Path, visited: set[Path] | None = None) -> list[Requirement]:
    """Parse a pip requirements file and recursively follow -r includes."""
    if visited is None:
        visited = set()
    path = path.resolve()
    if path in visited:
        return []
    visited.add(path)

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as err:
        raise ValueError(f"Cannot read requirements file {path}: {err}") from err

    result: list[Requirement] = []
    continuation = ""
    for line_number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Strip comments, but retain URL fragments.
        line = re.sub(r"\s+#.*$", "", line).strip()
        if not line:
            continue
        if line.endswith("\\"):
            continuation += line[:-1].strip() + " "
            continue
        line = continuation + line
        continuation = ""

        include = re.match(r"^(?:-r|--requirement)(?:\s+|=)(.+)$", line)
        if include:
            include_path = (path.parent / include.group(1).strip()).resolve()
            result.extend(parse_requirements_file(include_path, visited))
            continue

        # Core's requirements files may contain pip options and editable/local refs.
        if line.startswith(("-", ".", "/")):
            continue

        # requirements files may include pip hash options.
        line = re.sub(r"\s+--hash(?:=|\s+)\S+", "", line).strip()
        try:
            result.append(Requirement(line))
        except InvalidRequirement as err:
            raise ValueError(
                f"{path}:{line_number}: invalid requirement {line!r}: {err}"
            ) from err

    if continuation:
        raise ValueError(f"{path}: unfinished line continuation at end of file")
    return result


def parse_declarations(source: str, declarations: list[str]) -> list[Requirement]:
    """Parse PEP 508 dependency strings."""
    requirements = []
    for declaration in declarations:
        try:
            requirements.append(Requirement(declaration))
        except InvalidRequirement as err:
            raise ValueError(
                f"{source}: invalid dependency {declaration!r}: {err}"
            ) from err
    return requirements


def poetry_constraint(constraint: str) -> str:
    """Convert a Poetry version constraint to a PEP 440 specifier."""
    specifiers = []
    for part in re.split(r"\s*,\s*|\s+", constraint.strip()):
        if not part or part == "*":
            continue
        if part[0] not in "^~":
            specifiers.append(part if part[0] in "<>=!" else f"=={part}")
            continue
        if part.startswith("~="):
            specifiers.append(part)
            continue
        operator, version = part[0], part[1:]
        try:
            release = list(Version(version).release)
        except InvalidVersion as err:
            raise ValueError(f"invalid Poetry constraint {part!r}") from err
        if operator == "^":
            # Bump the first non-zero component: ^1.2.3 -> <2, ^0.2.3 -> <0.3
            index = next(
                (i for i, value in enumerate(release) if value),
                len(release) - 1,
            )
        else:
            # ~1.2.3 -> <1.3, ~1 -> <2
            index = min(1, len(release) - 1)
        upper = release[: index + 1]
        upper[index] += 1
        specifiers.append(f">={version}")
        specifiers.append(f"<{'.'.join(str(value) for value in upper)}")
    return ",".join(specifiers)


def parse_poetry(path: Path, dependencies: dict) -> list[Requirement]:
    """Read Poetry [tool.poetry.dependencies]."""
    declarations = []
    for name, spec in dependencies.items():
        if name.lower() == "python":
            continue
        if isinstance(spec, list):
            raise ValueError(
                f"{path}: multiple-constraint Poetry dependency {name!r} is not supported"
            )
        if isinstance(spec, dict):
            if spec.get("optional"):
                continue
            if "version" not in spec:
                # git/path/url dependencies have no comparable version
                continue
            spec = spec["version"]
        try:
            declarations.append(f"{name}{poetry_constraint(str(spec))}")
        except ValueError as err:
            raise ValueError(f"{path}: {name}: {err}") from err
    return parse_declarations(str(path), declarations)


def parse_pyproject(path: Path) -> list[Requirement] | None:
    """Read PEP 621 or Poetry dependencies, or None if none are declared."""
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as err:
        raise ValueError(f"Cannot read {path}: {err}") from err

    project = data.get("project", {})
    if "dependencies" in project:
        declarations = project["dependencies"]
        if not isinstance(declarations, list):
            raise ValueError(f"{path}: [project].dependencies must be a list")
        return parse_declarations(str(path), declarations)

    if "dependencies" in project.get("dynamic", []):
        dynamic = (
            data.get("tool", {}).get("setuptools", {}).get("dynamic", {})
        ).get("dependencies", {})
        files = dynamic.get("file", [])
        if isinstance(files, str):
            files = [files]
        if not files:
            raise ValueError(
                f"{path}: dependencies are dynamic but not declared via "
                "[tool.setuptools.dynamic] dependencies = {file = ...}"
            )
        requirements = []
        for file in files:
            requirements += parse_requirements_file(path.parent / file)
        return requirements

    poetry = data.get("tool", {}).get("poetry", {}).get("dependencies")
    if poetry is not None:
        return parse_poetry(path, poetry)

    return None


def parse_setup_cfg(path: Path) -> list[Requirement] | None:
    """Read setuptools [options] install_requires, or None if absent."""
    config = configparser.ConfigParser(interpolation=None)
    try:
        config.read(path, encoding="utf-8")
    except configparser.Error as err:
        raise ValueError(f"Cannot read {path}: {err}") from err
    if not config.has_option("options", "install_requires"):
        return None
    value = config.get("options", "install_requires").strip()
    if value.startswith("file:"):
        requirements = []
        for file in value.removeprefix("file:").split(","):
            requirements += parse_requirements_file(path.parent / file.strip())
        return requirements
    declarations = [
        line.strip()
        for line in value.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return parse_declarations(str(path), declarations)


def parse_setup_py(path: Path) -> list[Requirement] | None:
    """Statically read setup(install_requires=...) without executing setup.py."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as err:
        raise ValueError(f"Cannot read {path}: {err}") from err

    assignments: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value

    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", getattr(node.func, "attr", None)) == "setup"
        ):
            continue
        for keyword in node.keywords:
            if keyword.arg != "install_requires":
                continue
            value = keyword.value
            if isinstance(value, ast.Name):
                value = assignments.get(value.id, value)
            try:
                declarations = ast.literal_eval(value)
            except ValueError as err:
                raise ValueError(
                    f"{path}: install_requires is not a literal list; move "
                    "dependencies to requirements.txt or pyproject.toml"
                ) from err
            return parse_declarations(str(path), list(declarations))
        return None
    return None


def is_active(requirement: Requirement) -> bool:
    """Evaluate environment markers on the current runner."""
    return requirement.marker is None or requirement.marker.evaluate()


def pinned_versions(requirements: list[Requirement]) -> set[Version]:
    """Extract exact, non-wildcard PEP 440 pins."""
    versions: set[Version] = set()
    for requirement in requirements:
        for specifier in requirement.specifier:
            if specifier.operator != "==" or "*" in specifier.version:
                continue
            try:
                versions.add(Version(specifier.version))
            except InvalidVersion:
                continue
    return versions


def released_versions(pypi_url: str, name: str) -> list[Version]:
    """Return the non-yanked, final releases of a package on PyPI."""
    url = f"{pypi_url.rstrip('/')}/{name}/json"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            releases = json.load(response)["releases"]
    except (OSError, ValueError, KeyError) as err:
        raise ValueError(f"cannot read PyPI release list for {name}: {err}") from err

    versions = []
    for version, files in releases.items():
        if not files or all(file.get("yanked") for file in files):
            continue
        try:
            parsed = Version(version)
        except InvalidVersion:
            continue
        if not parsed.is_prerelease:
            versions.append(parsed)
    return versions


def main() -> int:
    """Run the compatibility check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--setup-cfg", type=Path, default=Path("setup.cfg"))
    parser.add_argument("--setup-py", type=Path, default=Path("setup.py"))
    parser.add_argument("--library-requirements", type=Path, default=Path("requirements.txt"))
    parser.add_argument(
        "--core-requirements",
        type=Path,
        action="append",
        required=True,
        help="Core requirements or constraints file; repeat for several files",
    )
    parser.add_argument("--pypi-url", default="https://pypi.org/pypi")
    parser.add_argument("--core-ref", default="unknown")
    parser.add_argument("--missing-policy", choices=("warn", "fail"), default="warn")
    args = parser.parse_args()

    print("### HA CORE DEPENDENCY COMPATIBILITY CHECK VERSION 1.1.0 ###")
    print(f"Core ref: {args.core_ref}")
    for path in args.core_requirements:
        print(f"Core requirements: {path}")
    print(f"Missing dependency policy: {args.missing_policy}")
    print()

    sources = (
        (args.pyproject, parse_pyproject),
        (args.setup_cfg, parse_setup_cfg),
        (args.setup_py, parse_setup_py),
        (args.library_requirements, parse_requirements_file),
    )
    library: list[Requirement] = []
    found = False
    try:
        for path, parse in sources:
            if not path.is_file():
                continue
            requirements = parse(path)
            if requirements is None:
                print(f"{path}: no dependency declarations")
                continue
            found = True
            print(f"{path}: {len(requirements)} dependencies")
            library += requirements
        if not found:
            raise ValueError(
                "No dependency declarations found in "
                + ", ".join(str(path) for path, _ in sources)
            )
        core: list[Requirement] = []
        for path in args.core_requirements:
            core += parse_requirements_file(path)
    except ValueError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    print()

    library_by_name: dict[str, list[Requirement]] = defaultdict(list)
    core_by_name: dict[str, list[Requirement]] = defaultdict(list)
    for requirement in library:
        if is_active(requirement):
            library_by_name[canonicalize_name(requirement.name)].append(requirement)
    for requirement in core:
        if is_active(requirement):
            core_by_name[canonicalize_name(requirement.name)].append(requirement)

    failures: list[str] = []
    warnings: list[str] = []
    checked = 0

    for name in sorted(library_by_name):
        core_entries = core_by_name.get(name, [])
        if not core_entries:
            message = f"{name}: not declared by HA Core; version comparison skipped"
            (warnings if args.missing_policy == "warn" else failures).append(message)
            continue

        core_pins = pinned_versions(core_entries)
        if not core_pins:
            core_range = SpecifierSet()
            for entry in core_entries:
                core_range &= entry.specifier
            for library_req in library_by_name[name]:
                if not library_req.specifier or not core_range:
                    continue
                checked += 1
                try:
                    versions = released_versions(args.pypi_url, name)
                except ValueError as err:
                    warnings.append(f"{name}: {err}; comparison skipped")
                    continue
                if not any(
                    library_req.specifier.contains(version)
                    and core_range.contains(version)
                    for version in versions
                ):
                    failures.append(
                        f"{name}: library requires {library_req.specifier}; "
                        f"Core requires {core_range}; no release satisfies both"
                    )
            continue

        for library_req in library_by_name[name]:
            if not library_req.specifier:
                continue
            checked += 1
            incompatible = sorted(
                (version for version in core_pins
                 if not library_req.specifier.contains(version, prereleases=True)),
                reverse=True,
            )
            if len(incompatible) == len(core_pins):
                core_text = ", ".join(str(version) for version in sorted(core_pins))
                failures.append(
                    f"{name}: library requires {library_req.specifier}; "
                    f"Core pins {core_text}"
                )

    for warning in warnings:
        print(f"WARNING: {warning}")
    for failure in failures:
        print(f"FAIL: {failure}")

    print()
    print(f"Dependency constraints checked: {checked}")
    print(f"Warnings: {len(warnings)}")
    print(f"Failures: {len(failures)}")
    if failures:
        print("\nDependency compatibility check FAILED.")
        return 1
    print("\nDependency compatibility check PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
