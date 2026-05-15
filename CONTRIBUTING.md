# Contributing to vrcpilot

Thanks for your interest in contributing! `vrcpilot` automates the desktop client and in-world interactions of VRChat from Python. This document covers what we expect from a pull request and how to set up a development environment.

## Scope

`vrcpilot` is intentionally narrow:

- **In scope**: launching / terminating VRChat, window focus, screen capture, OCR, image-template detection, synthetic keyboard / mouse input, clipboard-based text injection.
- **Out of scope**: anything that requires reverse-engineering the VRChat network protocol, modifying the VRChat client binary, distributing client assets, or automating account-level destructive actions (logout, friend management, avatar uploads, purchases). Please do not file PRs in those directions.

When automating gameplay, **be considerate of other players**. Public instances are shared spaces. The `tests/e2e/` scenarios deliberately stay within non-destructive operations and we expect contributions to follow the same posture.

## Development setup

We use [uv](https://docs.astral.sh/uv/) for environment and dependency management, and [just](https://just.systems/) as a task runner. Python 3.12 or later is required.

```bash
just setup       # uv venv + uv sync --all-extras + pre-commit install
```

If you are not using `just`, the equivalent is:

```bash
uv venv
uv sync --all-extras
uv run pre-commit install
```

### Platform notes

- **Windows**: no extra system packages; `pywin32` and `pydirectinput` are installed automatically.

- **Linux**: [`inputtino-python`](https://github.com/games-on-whales/inputtino/tree/stable/bindings/python) is built natively from git. Install build prerequisites first:

  ```bash
  sudo apt-get install -y cmake build-essential pkg-config libevdev-dev
  sudo usermod -aG input "$USER"   # for /dev/uinput access; log out and back in
  ```

  An X11 or XWayland session is required for window-related code. Wayland-native sessions are not supported.

- **macOS**: not supported.

## Project layout

- Source: [`src/vrcpilot/`](src/vrcpilot/) — a typed package (`py.typed`).
- Tests: [`tests/`](tests/) mirror `src/vrcpilot/` one-to-one (`src/vrcpilot/foo.py` ↔ `tests/vrcpilot/test_foo.py`). End-to-end scenarios live in [`tests/e2e/`](tests/e2e/).
- CLI entry point: `vrcpilot.cli:main`, dispatched through [`src/vrcpilot/cli/__init__.py`](src/vrcpilot/cli/__init__.py).
- Public docs: [`docs/`](docs/) holds the hand-written reference and tutorial that the README links into ([`docs/cli.md`](docs/cli.md), [`docs/python-api.md`](docs/python-api.md), [`docs/usage.md`](docs/usage.md)). Update them when you change the CLI or public API surface.

## Branching and commits

- Branch off `main` using `<type>/<YYYYMMDD>/<topic>`, for example `feat/20260506/world-search` or `fix/20260506/launch-timeout`.
- Allowed types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`.
- Commit messages follow `<type>(<scope>): <subject>` (Conventional Commits flavor). Keep one logical change per commit.
- Do not commit directly to `main`; merging is done through pull requests.

### Branching strategy

- `main` is the only long-lived development branch. All feature, fix, refactor, docs, test, and chore work starts from `main` using the `<type>/<YYYYMMDD>/<topic>` convention above.
- Each minor series gets a long-lived `release/<x.y>` branch (for example `release/0.1`, `release/0.2`, `release/1.0`). These branches are cut from `main` when the first stable of a new minor series ships and are **never deleted** — they remain the home for any subsequent patch releases of that series.
- We do not maintain a separate `stable` branch. The most recent stable tag on PyPI is the source of truth for "what is stable"; if you need to install the latest stable, install by version or simply `pip install vrcpilot`.
- Hotfix branches are an exception to the "branch off `main`" rule — see the [Hotfix process](#hotfix-process) below.

### Tag conventions

- Releases are driven entirely by Git tags. Tags use SemVer with a `v` prefix: `v0.1.0`, `v0.2.0`, `v1.0.0`.
- Pre-release tags follow PEP 440: `v0.1.0a1` (alpha), `v0.1.0b1` (beta), `v0.1.0rc1` (release candidate). The publish workflow detects the `a`/`b`/`rc` suffix and marks the resulting GitHub Release as a pre-release.
- Pushing any tag matching `v*` triggers the publish workflow (`.github/workflows/publish.yml`), which performs the Test PyPI → PyPI → GitHub Release chain. Do not create `v*` tags casually.
- The tag and the `version` field in `pyproject.toml` must match exactly (minus the leading `v`); the workflow's build step refuses to proceed otherwise.

### Release process (regular)

For a normal release on `main` (new minor or new stable from an existing series):

1. On a `chore/<YYYYMMDD>/release-vX.Y.Z` branch off `main`, bump `version` in `pyproject.toml`, refresh `uv.lock` (`uv lock`), and update `CHANGELOG.md` with a section for the new version.
2. Run `just run` and confirm everything passes. Open a PR into `main`.
3. After the release PR merges into `main`:
   - If this is the first release of a new minor series (`x.y.0`), create `release/x.y` from the current `main` HEAD. Once created, this branch is permanent.
   - If this minor series already has a `release/x.y` branch, fast-forward it to include the release commit (or merge `main` into it).
4. On `release/x.y`, create the annotated tag `vX.Y.Z` and push it. For a brand-new minor series, the `main` and `release/x.y` HEADs may be identical at this point — that is fine; the tag still lives on `release/x.y`.
5. The publish workflow runs: it verifies the tag matches the project version, builds the sdist and wheel, publishes to Test PyPI, then PyPI, then creates a GitHub Release with the extracted changelog notes.

### Hotfix process

Hotfixes target an already-released minor series and must **not** be developed on `main`:

1. Create `fix/<YYYYMMDD>/<topic>` from the relevant `release/x.y` branch (not from `main`). This isolates the fix from any unreleased work that has since landed on `main`.
2. Implement and verify with `just run`. Open a PR targeting `release/x.y`.
3. After the PR merges, bump the patch component on `release/x.y` (update `pyproject.toml`, `uv.lock`, and `CHANGELOG.md`), tag `vX.Y.(Z+1)` on `release/x.y`, and push the tag to trigger publish.
4. Open a follow-up PR `chore/<YYYYMMDD>/backport-vX.Y.(Z+1)` that cherry-picks the fix (and changelog entry) onto `main` so the fix is not lost in the next minor release.
5. The hotfix PR description must include a `[ ] cherry-picked to main` checkbox. Do not close the hotfix PR — or consider the hotfix complete — until that box is checked and the backport PR has merged.

### Pre-release tags

- Pre-release tags (`vX.Y.Za1`, `vX.Y.Zb1`, `vX.Y.Zrc1`) may be cut from either `main` or a `release/x.y` branch, depending on what is being validated.
- They flow through the same workflow path and end up on PyPI just like stable releases, but `pip install vrcpilot` ignores them by default (users opt in with `pip install --pre vrcpilot`), so they are safe to publish without surprising downstream users.
- Use pre-release tags freely to rehearse the publish pipeline itself — verifying Trusted Publishing, environments, the tag/version guard, and changelog extraction — before committing to a stable tag.

## Verifying changes

Every PR is expected to pass:

```bash
just run         # format + test + type check (alias for the three below)
```

If you prefer to run them individually:

```bash
just format      # pre-commit (ruff fix + format, mdformat, codespell, ...)
just test        # pytest -v --cov
just type        # pyright (strict on src/, tests/ excluded)
```

The CI matrix runs on Linux and Windows across Python 3.12 / 3.13 / 3.14. New code must work on both platforms or be guarded with a clear `sys.platform` check.

### Tests

- Mirror the source layout: `src/vrcpilot/foo.py` ↔ `tests/vrcpilot/test_foo.py`. Backend-split modules (`window/win32.py`, `window/x11.py`) get split tests too.
- Prefer real objects and real I/O; reach for mocks only at true external boundaries (network APIs, hard-to-reproduce kernel features). For ABC-only modules, define a tiny concrete `Impl` in `tests/helpers.py` rather than mocking.
- For tests that depend on a platform or display, `pytest.skip(..., allow_module_level=True)` at the top of the file (before any imports that would fail at collection time).

### End-to-end scenarios

Files under [`tests/e2e/`](tests/e2e/) are scenario scripts that drive a real VRChat instance. They are excluded from `pytest` collection. Run them via:

```bash
just e2e-test <NAME>   # e.g. just e2e-test focus_unfocus
```

Requirements: Steam must already be running, VRChat must be installed, and on Linux the desktop session must be X11 or XWayland.

## Pull requests

- Title: `<type>(<scope>): <subject>` mirroring the commit convention.
- Description: follow [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md).
- One PR per concern — please do not bundle unrelated changes.
- Confirm `just run` passes locally before requesting review.

## Reporting issues

- Bug reports and feature requests: open an issue using the templates under [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/).
- Security vulnerabilities: please use [GitHub Security Advisories](https://github.com/MLShukai/vrcpilot/security/advisories/new) instead of a public issue.

## License

By contributing, you agree that your contributions will be licensed under the MIT License (see [`LICENSE`](LICENSE)).
