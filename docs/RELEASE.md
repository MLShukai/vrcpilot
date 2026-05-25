# Release Runbook

This is the hands-on runbook for the engineer cutting a `vrcpilot` release. The release policy (branching, tag conventions, hotfix rules) lives in [`CONTRIBUTING.md`](../CONTRIBUTING.md); this document is the step-by-step companion you follow during an actual release.

The pipeline is tag-driven: pushing a `v*` tag triggers [`.github/workflows/publish.yml`](../.github/workflows/publish.yml), which builds, publishes to Test PyPI, publishes to PyPI, and creates a GitHub Release. Authentication uses PyPI Trusted Publishing (OIDC) — no long-lived tokens.

______________________________________________________________________

## 1. One-time setup

Do these once when bootstrapping the release pipeline (or after rotating organization/repo names). They are the prerequisites for every later step in this document.

### 1.1 Register pending publishers on PyPI and Test PyPI

PyPI's Trusted Publishing matches GitHub Actions to a project via an OIDC claim. The matching record must exist before the first publish.

On [pypi.org](https://pypi.org) → Account settings → Publishing → **Add a new pending publisher**:

| Field         | Value         |
| ------------- | ------------- |
| PyPI project  | `vrcpilot`    |
| Owner         | `MLShukai`    |
| Repository    | `vrcpilot`    |
| Workflow name | `publish.yml` |
| Environment   | `pypi`        |

Repeat on [test.pypi.org](https://test.pypi.org) with **Environment = `testpypi`**.

Why pending: the project does not exist yet on first release. The pending record converts to a regular Trusted Publisher the moment the first successful upload completes.

### 1.2 Create GitHub Environments

In repo Settings → Environments, create two environments whose names match the publisher registrations above:

- `pypi`
- `testpypi`

Without these environments, `pypa/gh-action-pypi-publish` cannot obtain the OIDC token and the job fails before any upload.

### 1.3 Add a Required reviewer to `pypi` (recommended)

In `pypi` environment settings, set **Required reviewers** to at least one trusted maintainer.

Why: this is the final manual gate before code actually reaches public PyPI. A mistyped tag or a botched cherry-pick is recoverable up to this point; after upload it is not (see [Section 5](#5-rollback--failure-matrix)). Leave `testpypi` open for fast iteration.

### 1.4 Protect `release/x.y` branches (recommended)

For each long-lived release branch (`release/0.1`, `release/0.2`, ...), enable a Branch protection rule:

- Require pull request before merging.
- Disallow direct pushes.
- Disallow force pushes.

Why: tags pushed to a release branch are what trigger the workflow. Keeping the branch immune to accidental rewrites means the tag never resolves to a surprise commit.

______________________________________________________________________

## 2. Regular release checklist

Use this for any normal release: a first minor (`0.2.0`), a subsequent minor (`0.3.0`), or an in-series patch (`0.2.1`). Hotfixes have their own track in [Section 3](#3-hotfix-release-checklist).

Once the project hits `1.0.0`, every minor release **must be rehearsed** with a release candidate first; see [Section 4](#4-rehearsal-protocol). In the `0.x` series rehearsal is recommended but optional — while there are no production users, the cost of cutting `vX.Y.0` directly without an `rcN` is bounded, and the rehearsal can be skipped for small, scoped minors. The steps below are the post-rehearsal flow for the stable tag (and also the direct-to-stable flow when rehearsal is skipped).

### 2.1 Prepare the release commit

On a topic branch off `main`:

```bash
git switch main && git pull
git switch -c chore/$(date +%Y%m%d)/release-vX.Y.Z
```

1. Bump `[project].version` in `pyproject.toml` to `X.Y.Z`. The build-time tag-vs-pyproject guard rejects mismatches, so a typo here surfaces as a workflow failure rather than a bad publish.
2. Update `[project].classifiers` if the maturity has changed (e.g. `Development Status :: 3 - Alpha` → `4 - Beta` when leaving `0.x.0a*` series; `5 - Production/Stable` at `1.0.0`).
3. Run `uv lock` so `uv.lock` matches the bumped version.
4. Add a new section to `CHANGELOG.md` in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format: header `## [X.Y.Z] - YYYY-MM-DD`, with `### Added` / `### Changed` / `### Fixed` / `### Removed` as appropriate. Move entries from `[Unreleased]` into the new section and update the compare-link footer.

Why one commit per concern: the workflow's GitHub Release step extracts notes by matching `## [X.Y.Z]` in `CHANGELOG.md`. A missing or differently-shaped header silently produces a generic "Release X.Y.Z" body.

### 2.2 Verify locally

```bash
just run               # format + test + type, all must pass
uv build               # produces dist/vrcpilot-X.Y.Z{.tar.gz,-py3-none-any.whl}
uv run twine check dist/*
```

`twine check` catches metadata issues (long-description rendering, license classifier, etc.) that PyPI will reject server-side. Fix locally; do not ship a tag and hope.

### 2.3 Merge and branch

1. Open a PR targeting `main`. Merge once green.

2. If this is the first release in a new minor series (`X.Y.0`), create the long-lived release branch from `main`:

   ```bash
   git switch main && git pull
   git switch -c release/X.Y
   git push -u origin release/X.Y
   ```

   For patch releases (`X.Y.Z` with `Z > 0`), reuse the existing `release/X.Y` branch — see [Section 3](#3-hotfix-release-checklist).

### 2.4 Tag and push

```bash
git switch release/X.Y && git pull
git tag vX.Y.Z
git push origin vX.Y.Z
```

The tag is what the workflow listens for (`on: push: tags: ['v*']`). Pushing the branch first and then the tag avoids a race where the tag exists on the remote but the matching commit does not.

### 2.5 Watch the workflow

In GitHub Actions, observe in order:

1. **build** — verifies tag matches `pyproject.toml`, runs `uv build`, uploads artifacts.
2. **publish-to-testpypi** — uploads to Test PyPI.
3. **publish-to-pypi** — paused if Required reviewers are set on `pypi`; approve when you are sure the Test PyPI upload looks right.
4. **github-release** — signs artifacts with sigstore, extracts the CHANGELOG section, and creates the Release.

Sanity checks after all four jobs are green:

- Test PyPI: `https://test.pypi.org/project/vrcpilot/X.Y.Z/` renders.
- PyPI: `https://pypi.org/project/vrcpilot/X.Y.Z/` renders.
- GitHub Releases: `vX.Y.Z` exists, notes match `CHANGELOG.md`, `.sigstore.json` assets attached.
- In a clean environment: `pip install vrcpilot==X.Y.Z` resolves and `python -c "import vrcpilot; print(vrcpilot.__version__)"` prints `X.Y.Z`.

______________________________________________________________________

## 3. Hotfix release checklist

For an in-series patch addressing a regression already on PyPI. The fix lands on the affected `release/X.Y` first, then is forward-ported to `main`.

### 3.1 Branch off the release line

```bash
git switch release/X.Y && git pull
git switch -c fix/$(date +%Y%m%d)/<topic>
```

Never branch a hotfix off `main`: `main` may have already moved on with breaking changes that do not belong in a patch.

### 3.2 Fix, PR, merge into release/X.Y

Write the fix and its tests. `just run` must pass. Open a PR **targeting `release/X.Y`**, not `main`. Merge.

### 3.3 Tag the patch

```bash
git switch release/X.Y && git pull
git tag vX.Y.$((Z+1))
git push origin vX.Y.$((Z+1))
```

The workflow then runs end-to-end as in [Section 2.5](#25-watch-the-workflow).

### 3.4 Forward-port to main

Open a separate PR that brings the fix into `main`:

```bash
git switch main && git pull
git switch -c chore/$(date +%Y%m%d)/backport-vX.Y.$((Z+1))
git cherry-pick <commit>            # the hotfix commit(s) from release/X.Y
```

In the PR description, **always include a checklist item**:

```
- [ ] cherry-picked to main
```

Tick it once the backport PR merges. This is the only reliable signal that `main` and the active `release/X.Y` are no longer divergent on the fix; release branches outlive any one engineer's memory.

If `main` has reworked the affected code and the cherry-pick does not apply cleanly, write the equivalent fix by hand. The point of the checkbox is that the fix is *present in main*, not that the commit hash matches.

______________________________________________________________________

## 4. Rehearsal protocol

From `1.0.0` onwards, every new minor (`X.Y.0`) is rehearsed with a release candidate before its stable tag is pushed. In the `0.x` series the rehearsal is recommended but not mandatory — while the user base is empty or experimental, the operational cost of skipping it (a botched `vX.Y.0` is recoverable by tagging `vX.Y.1` immediately) is acceptable, and small minors may go direct-to-stable. When you do run a rehearsal, it exists to surface authentication, environment, tag-guard, and CHANGELOG-extraction problems against the *real* infrastructure — not a mock.

### 4.1 Cut an `rcN` tag

1. Follow [Section 2.1 – 2.3](#21-prepare-the-release-commit) but bump `pyproject.toml` to `X.Y.0rc1` and add a `## [X.Y.0rc1] - YYYY-MM-DD` section to `CHANGELOG.md`. Keep the `Development Status` classifier conservative for prereleases (`3 - Alpha` is fine).
2. Merge into `main`, then create `release/X.Y` if it does not exist.
3. Tag `vX.Y.0rc1` on `release/X.Y` and push.

Why `rcN` and not `aN`/`bN`: the workflow's `--prerelease` switch fires on any PEP 440 prerelease suffix (`a`/`b`/`rc` + digits), but `rc` is the term that signals to consumers "this is a release candidate, not exploratory alpha". Use the others only if you genuinely want to publish exploratory builds.

### 4.2 Verify the full chain

The rehearsal passes only when **every** check below succeeds for `rcN`:

- All four workflow jobs (build / publish-to-testpypi / publish-to-pypi / github-release) green.

- Test PyPI lists `X.Y.0rcN`.

- PyPI lists `X.Y.0rcN`.

- GitHub Release `vX.Y.0rcN` exists, marked as prerelease, with sigstore assets and CHANGELOG-derived notes.

- In a clean environment:

  ```bash
  pip install --pre vrcpilot==X.Y.0rcN
  python -c "import vrcpilot; print(vrcpilot.__version__)"   # prints X.Y.0rcN
  ```

  The `--pre` is required: `pip` ignores prereleases by default, which is also why prerelease tags are safe to ship publicly without disturbing stable users.

If any check fails: read the failure matrix in [Section 5](#5-rollback--failure-matrix), apply the fix on `release/X.Y`, and **bump to `rcN+1`**. Do not reuse the failed `rcN` number — Test PyPI and PyPI both forbid republishing the same version (see [Section 6](#6-pypi-republish-prohibition)).

### 4.3 Promote to stable

Once the latest `rcN` passes every check, push the stable tag from the same `release/X.Y`:

```bash
git switch release/X.Y && git pull
# Open a small PR that bumps version to X.Y.0, adjusts classifiers,
# and adds the `## [X.Y.0]` CHANGELOG section. Merge it into release/X.Y.
git tag vX.Y.0
git push origin vX.Y.0
```

The stable tag re-runs the same workflow against the same infrastructure that just succeeded for the rc — there are no surprises.

______________________________________________________________________

## 5. Rollback / failure matrix

What to do when a step goes wrong. Triage by the **first** failing job.

| Failure                                                      | What is published?                    | Recovery                                                                                                                                                                                                                     |
| ------------------------------------------------------------ | ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `build` job fails (tag vs `pyproject` mismatch, build error) | Nothing.                              | Delete the tag (`git push origin :vX.Y.Z` then `git tag -d vX.Y.Z`), fix the cause, re-push the *same* tag. Since nothing reached any index, reusing the version number is safe.                                             |
| `publish-to-testpypi` fails                                  | Nothing on PyPI.                      | Test PyPI **also** forbids republishing the same version. Bump to the next number (`vX.Y.0rcN+1` during rehearsal, or `vX.Y.(Z+1)` for stable patches) and start over. Do **not** delete and re-push the same tag.           |
| `publish-to-pypi` fails after Test PyPI succeeded            | Only on Test PyPI.                    | Same rule as above: PyPI will refuse the version forever once Test PyPI took it. Bump to the next number on `release/X.Y` and tag again.                                                                                     |
| `publish-to-pypi` succeeds but `github-release` fails        | PyPI **and** Test PyPI.               | The version is already shipped — **do not** bump it. Re-run the failed job from the Actions UI (most transient errors clear), or create the release manually with `gh release create vX.Y.Z --notes-file <notes>.md dist/*`. |
| Bug discovered after PyPI publish                            | PyPI (everyone can `pip install` it). | On PyPI Web UI, **yank** the bad version (do not delete it; see [Section 6](#6-pypi-republish-prohibition)). Then run the hotfix flow in [Section 3](#3-hotfix-release-checklist) to ship `vX.Y.(Z+1)` with the fix.         |

Note that the "bump to the next number" rule covers both rc and stable: a failed `v0.2.0` upload is followed by `v0.2.1`, not a re-attempt of `v0.2.0`. This is why the rehearsal in [Section 4](#4-rehearsal-protocol) matters — burning an rc number is cheap, burning the `.0` of a stable minor is awkward.

______________________________________________________________________

## 6. PyPI republish prohibition

PyPI and Test PyPI both treat version numbers as **single-use forever**. Two consequences:

- **Yank, do not delete.** A *yank* hides a release from default `pip install` resolution but keeps the metadata and lets pinned installs continue to work. A *delete* frees nothing — the number remains permanently un-republishable — and any project still pinned to that version breaks.
- **Never reuse a failed number.** If `v0.2.0rc1` failed mid-pipeline and you want to retry, the next attempt is `v0.2.0rc2`. Test PyPI in particular has bitten projects that assumed "I deleted it on the server, so I can push the same number again" — it cannot.

Treat each tag push as a one-way commit, and you will not be surprised. The rehearsal flow ([Section 4](#4-rehearsal-protocol)) exists specifically so the *first* time you ever push `vX.Y.0` is a tag whose pipeline you have already watched succeed under `rcN`.
