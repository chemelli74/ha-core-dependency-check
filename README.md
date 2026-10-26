# Home Assistant Core dependency check

Reusable composite GitHub Actions for checking a Python library's runtime dependencies against the versions Home Assistant Core installs: `requirements_all.txt` and `homeassistant/package_constraints.txt`.

Three actions are provided:

| Action | Compares against |
|---|---|
| `chemelli74/ha-core-dependency-check/dev@f58f468f97ba4a0a2cd0e62dd9864baf9445d77c # v1.1.0` | the `dev` branch of Home Assistant Core |
| `chemelli74/ha-core-dependency-check/release@f58f468f97ba4a0a2cd0e62dd9864baf9445d77c # v1.1.0` | the latest published Home Assistant Core release (resolved via the GitHub releases API) |
| `chemelli74/ha-core-dependency-check/label@c036686f47c5badcb254d5cd3c93344ea8dd0bf8 # v1.2.0` | `dev` or the latest release, chosen by a pull request label, only when the pull request changes dependencies |

## One-line integration

Add one or both steps to an existing job in `.github/workflows/ci.yaml`:

```yaml
- uses: chemelli74/ha-core-dependency-check/dev@f58f468f97ba4a0a2cd0e62dd9864baf9445d77c # v1.1.0
- uses: chemelli74/ha-core-dependency-check/release@f58f468f97ba4a0a2cd0e62dd9864baf9445d77c # v1.1.0
```

By default, each action auto-detects how the library declares its dependencies and warns about dependencies that Core does not declare.

The action fails if a library's declared version constraint is not satisfied by the exact version pinned by Core. When Core only constrains a range (for example `typing-extensions>=4.16.0,<5.0`), it fails if no released version on PyPI satisfies both the library and Core.

Typical use: `release` tells you whether a new library version can be bumped in Core right now; `dev` tells you whether it will be compatible with the next Core release.

## Choosing the check with a pull request label

The `label` action runs one of the two checks, depending on which label the pull request has:

| Label | Check |
|---|---|
| `core-beta-release` | against Core `dev`: the change is meant for the next Core beta |
| `core-patch-release` | against the latest Core release: the change is meant for a Core patch release |

The check only runs when the pull request changes the library's declared dependencies: it compares them between the pull request's base commit and its head. Other changes, such as a new version number or tool settings in `pyproject.toml`, don't count. When dependencies are unchanged, the check is skipped and no label is needed.

When dependencies changed, the check fails with a "label missing" error if the pull request has neither label or both. On events other than pull requests (for example a push to `main`), it is skipped.

GitHub doesn't run `pull_request` workflows when labels change unless you ask for it, so add `labeled` and `unlabeled` to the trigger. A separate workflow keeps label changes from re-running the rest of your CI:

```yaml
name: Home Assistant Core dependencies

on:
  pull_request:
    types: [opened, synchronize, reopened, labeled, unlabeled]

permissions:
  contents: read

jobs:
  ha-core-dependencies:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: chemelli74/ha-core-dependency-check/label@c036686f47c5badcb254d5cd3c93344ea8dd0bf8 # v1.2.0
```

Both labels must exist in your repository.

## Supported dependency declarations

Every file that exists is read, and the dependencies found are combined. A missing file is skipped; the check fails only if no file declares any dependencies.

| Source | What is read |
|---|---|
| `pyproject.toml` | PEP 621 `[project].dependencies` |
| `pyproject.toml` | Dynamic dependencies via `[tool.setuptools.dynamic] dependencies = {file = [...]}` |
| `pyproject.toml` | Poetry `[tool.poetry.dependencies]` (`^`/`~` constraints are converted; `python`, optional, git and path dependencies are skipped) |
| `setup.cfg` | `[options] install_requires`, including `file:` references |
| `setup.py` | `setup(install_requires=...)` given as a literal list or a module-level variable holding one. The file is parsed, never executed |
| `requirements.txt` | Pip requirements, following `-r` includes |

## Optional configuration

```yaml
- uses: chemelli74/ha-core-dependency-check/release@f58f468f97ba4a0a2cd0e62dd9864baf9445d77c # v1.1.0
  with:
    pyproject: pyproject.toml
    requirements: requirements.txt
    missing-dependency-policy: warn
```

Inputs (same for all actions):

| Input | Default | Description |
|---|---|---|
| `pyproject` | `pyproject.toml` | Path to `pyproject.toml` (PEP 621 or Poetry) |
| `setup-cfg` | `setup.cfg` | Path to `setup.cfg` |
| `setup-py` | `setup.py` | Path to `setup.py` |
| `requirements` | `requirements.txt` | Path to library requirements |
| `missing-dependency-policy` | `warn` | `warn` or `fail` for dependencies absent from Core |

Outputs:

| Output | Description |
|---|---|
| `core-ref` | Core ref the dependencies were compared against (`dev` or the release tag, e.g. `2026.10.3`); empty when `label` skips the check |

## Requirements and behavior

- Requires a GitHub Actions runner with Python 3.13 available.
- Installs `packaging` for PEP 440 parsing.
- The `release` action uses the workflow's `github.token` to query the latest Core release, avoiding unauthenticated API rate limits.
- Downloads Core's `requirements_all.txt`, `requirements.txt` and `homeassistant/package_constraints.txt`; `-r` includes are followed. The constraints file pins transitive dependencies (for example `httpx`) that no integration declares directly.
- Evaluates environment markers on the runner.
- Does not install Home Assistant Core.
- Does not resolve dynamic build metadata or arbitrary pip options.
- For a Core dependency without an exact `==` pin, the release list is read from PyPI; yanked releases and pre-releases are ignored. If PyPI cannot be reached, the dependency is reported as a warning and skipped.

## Running locally

```bash
HA_CORE_REF=latest-release /path/to/ha-core-dependency-check/scripts/run.sh
```

`HA_CORE_REF` also accepts any Core branch, tag or commit. The action inputs map to the `PYPROJECT`, `SETUP_CFG`, `SETUP_PY`, `LIBRARY_REQUIREMENTS` and `MISSING_POLICY` environment variables.

Run the offline tests with `tests/test_fixtures.sh`, `tests/test_select_ref.sh` and `tests/test_deps_changed.sh`.
