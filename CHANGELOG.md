# Changelog

Notable changes in each release. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/). Each release's notes on GitHub
are taken from its section here (see CONTRIBUTING.md, *Releasing*).

## [Unreleased]

### Added
- Architecture guide (`docs/architecture.md`), API reference (`docs/api.md`), contributor guide
  (`CONTRIBUTING.md`) and this changelog. GitHub releases take their notes from it.
- `scripts/bump_version.py` sets the version everywhere at once; a test checks that every copy
  agrees.
- Issue and pull request templates, `.editorconfig` and `.gitattributes`.

### Changed
- Dependabot groups minor and patch updates into one weekly pull request per ecosystem.
- Development dependencies: vite 8.3.4, vitest 5.0.3, @vitejs/plugin-react 6.1.2, jsdom 30.1.2.

### Fixed
- The API reported version 0.6.0; it now reports the release version.
- Links point at the renamed repository (`Quantum-Chess-Engine`).

## [0.8.2] - 2026-10-12

### Changed
- The app is now called **Quantum Chess Engine**: window, installer, shortcuts and the macOS app
  name. The install folder, data folder and executable keep their names, so upgrades carry over
  settings and finished lessons, and the old shortcuts are replaced.

### Added
- `SECURITY.md`: how to report a vulnerability privately, and the known limitations.

## [0.8.1] - 2026-10-12

### Added
- **Get an internet link** in the desktop app: a free, temporary Cloudflare quick tunnel lets a
  friend anywhere join a hosted game. cloudflared is installed the first time (winget or
  Homebrew), and **Stop hosting** or closing the app closes the tunnel.

### Security
- Guests (on the network or through the tunnel) can reach only online games, never the host's
  games against the AI. At most 16 live feeds per game. The API docs are host-only.
- On Windows the tunnel closes with the app even if the app crashes.
- The app's local server answers only requests addressed to it (DNS rebinding).
- Pages can no longer open the dice-check dialog; it is in the Game menu only.

## [0.8.0] - 2026-10-12

### Added
- App icon.
- Desktop installers are built on pull requests that change the app.

### Changed
- Polished board and panel: framed board, probability chips and bars, a halo on superposed
  pieces, rings and dots for move targets, segmented controls, a status pill.
- Workflow actions updated to their latest major versions.

### Fixed
- The move dot of a square that was part of the last move sat in the square's corner.

### Security
- Hardening for hosting, the desktop window and builds: hosting is opt-in and stoppable, the
  window keeps to pages the app opened, and builds install hash-checked lock files.

## [0.7.0] - 2026-10-12

### Added
- Host and join games from the desktop app, with dice seeded by both players and verifiable
  afterwards (**Game ▸ Verify this game's dice**).

## [0.6.1] - 2026-10-12

### Changed
- The desktop release ships installers instead of zip files.

### Fixed
- Without a console, the desktop app logs output and errors to a file.

## [0.6.0] - 2026-10-12

The first release.

### Added
- Classical bitboard chess engine (perft-verified) and the quantum layer: split, merge, slide,
  measurement and entanglement, simulated with Cirq in a sparse, grouped register.
- REST API (FastAPI) with a live WebSocket feed, and a Docker image.
- MCTS AI with threat-aware evaluation, root lookahead and three strength levels.
- React + TypeScript visualizer with a seven-lesson tutorial.
- Online games with a friend, and a desktop app for Windows and macOS.
- Multi-level splits, check warnings and draw rules.

[Unreleased]: https://github.com/Andreas-Erick/Quantum-Chess-Engine/compare/v0.8.2...HEAD
[0.8.2]: https://github.com/Andreas-Erick/Quantum-Chess-Engine/compare/v0.8.1...v0.8.2
[0.8.1]: https://github.com/Andreas-Erick/Quantum-Chess-Engine/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/Andreas-Erick/Quantum-Chess-Engine/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/Andreas-Erick/Quantum-Chess-Engine/compare/v0.6.1...v0.7.0
[0.6.1]: https://github.com/Andreas-Erick/Quantum-Chess-Engine/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/Andreas-Erick/Quantum-Chess-Engine/releases/tag/v0.6.0
