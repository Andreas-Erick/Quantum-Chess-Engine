# Contributing

Thanks for your interest! This guide covers setting up, running the checks, the conventions the
code follows, and how releases are made. Start with [docs/architecture.md](docs/architecture.md)
for how the project fits together.

Found a security problem? Please don't open an issue: follow [SECURITY.md](SECURITY.md).

## Setup

You need Python 3.10 or newer and Node.js 24.

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt                     # the server, the engine and the tools
cd ui && npm ci && cd ..                                # the UI
```

For the desktop app, also `pip install -r requirements-desktop.txt`.

## Running

```bash
uvicorn api.server:app --reload             # API on :8000 (serves ui/dist if it is built)
cd ui && npm run dev                        # UI with hot reload on :5173, proxying to :8000
cd ui && npm run build                      # build ui/dist, which the server and desktop app serve
python -m desktop                           # the desktop app, from source (build the UI first)
python -m agent.arena --games 40 --a iterations=400 --b iterations=100   # AI strength match
```

## Checks

CI runs these on every pull request, on Python 3.10, 3.12, 3.13 and 3.14, and they must pass
before merging:

```bash
ruff check . && ruff format --check .       # lint and formatting (ruff format --write fixes it)
mypy                                        # type check (settings in pyproject.toml)
pytest -q --cov                             # tests, and coverage of at least 85%
cd ui && npm run lint && npm test && npm run build   # Biome lint + format, tests, types, build
```

Run them automatically before each commit with [pre-commit](https://pre-commit.com/). It uses
the same tools from your environment, so activate the virtual environment first:

```bash
pre-commit install                          # once
pre-commit run --all-files                  # any time
```

`ruff check --fix`, `ruff format` and `npm run format` (in `ui/`) fix most findings themselves.
Pull requests that change the app also build the Windows and macOS installers.

## Conventions

- **Tests come with the change.** Engine behaviour is tested in the engine
  (`tests/test_superposition.py`, `tests/test_entanglement.py`, …), endpoints in
  `tests/test_api.py`, and UI behaviour in `ui/src/*.test.tsx`. A bug fix starts with a test
  that fails without it.
- **Layers import downwards only**: `engine` ← `agent` ← `api` ← `desktop`.
  `tests/test_architecture.py` checks it.
- **The JSON contract lives in `api/schemas.py`** and is mirrored in `ui/src/types.ts`. Change
  both together. Give every new string field a length limit.
- **Comments explain why**, not what: the reason for a limit, the attack a check prevents, the
  invariant a function relies on. Docstrings say what a function promises.
- **Style** is automatic: Ruff formats Python (100 columns) and Biome formats TypeScript and CSS
  (120 columns, double quotes, semicolons). `.editorconfig` sets the basics for other files.
- **Types**: Python code is type-checked by mypy and the UI by TypeScript. When a value can be
  missing only in some cases (a move's second target, say), give it an accessor that states the
  rule, like `QuantumMove.split_targets`, rather than silencing the checker.
- **Commit messages**: an imperative subject line ("Add …", "Fix …") of at most about 70
  characters, then a body that explains what changed and why, wrapped at 72.
- **Dependencies**: `requirements*.txt` give version ranges, and CI tests the newest versions in
  them. The Docker image and desktop releases install from `requirements.lock` and
  `requirements-desktop.lock` (exact versions with hashes). After changing a requirements file,
  regenerate its lock with the `uv pip compile` command in the lock's header.

## Pull requests

1. Branch from `main` and keep each pull request to one topic.
2. Add an entry under **Unreleased** in [CHANGELOG.md](CHANGELOG.md) if users or contributors
   would notice the change.
3. Open the pull request. The template lists what reviewers look for.
4. `main` is protected: the tests, UI checks and Docker build must pass before merging.

## Releasing

Releases are cut from `main` by pushing a version tag. The `Desktop app` workflow builds the
installers and publishes the GitHub release, with that version's CHANGELOG section as its notes.

1. **Pick the version** ([SemVer](https://semver.org/)): bug fixes → patch (0.8.2 → 0.8.3), new
   features → minor (0.8.2 → 0.9.0).
2. **Prepare it in a pull request**:
   ```bash
   python scripts/bump_version.py 0.9.0
   ```
   In `CHANGELOG.md`, rename **Unreleased** to `[0.9.0] - YYYY-MM-DD`, add a fresh empty
   **Unreleased** above it, and update the comparison links at the bottom. CI fails if the new
   version has no CHANGELOG section.
3. **Merge it, then check that `main` has everything** the release should contain before
   tagging. A pull request merged early leaves later commits behind:
   ```bash
   git checkout main && git pull
   git log --oneline -5
   ```
4. **Tag and push**:
   ```bash
   git tag -a v0.9.0 -m "v0.9.0" && git push origin v0.9.0
   ```
5. **Watch the release** (`gh run watch`, or the Actions tab) until the installers are attached.
   If something is wrong, cancel the run before the `release` job publishes.
