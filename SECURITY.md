# Security policy

Quantum Chess Engine is a hobby project maintained by one person. It has had a security review, but no
professional audit. Please report problems privately so they can be fixed before they are
widely known.

## Reporting a vulnerability

Use **[Report a vulnerability](https://github.com/Andreas-Erick/Quantum-Chess-Engine/security/advisories/new)**
on the repository's Security tab. Please don't open a public issue for a security problem.

Include what an attacker could do, the steps to reproduce it, and the version you tested (the
release name, or a commit). You'll get an answer within a week. Fixes go into the next release,
and you'll be credited in it unless you'd rather not be.

## Supported versions

Only the [latest release](https://github.com/Andreas-Erick/Quantum-Chess-Engine/releases/latest) and
`main` get security fixes.

## What is in scope

The parts that face other people:

- **The desktop app's hosting**: the network listener (**Host a game**) and the internet link
  (**Get an internet link**). Guests should be able to join, watch and play the host's online
  games, and nothing else.
- **Joining**: a host's page runs in the joiner's window, and must not be able to make the
  joiner's app host, join, share, or show pages the app didn't open.
- **The server (API)**: seat tokens, the fair-dice scheme (`api/fairness.py`), and input
  handling.
- **Builds and releases**: the workflows in `.github/workflows` and the lock files.

## Known limitations

These are accepted and documented in the [README](README.md#privacy-and-security), so they don't
need a report:

- A public server has no request rate limiting, and anyone can start AI searches on it.
- An invite link is the seat: whoever opens it first gets it, and anyone with the game link can
  watch.
- When one player hosts, that player's app rolls the dice and could peek at upcoming outcomes.
- An internet link's traffic is relayed, and can be read, by Cloudflare.
- On macOS, a crashed app can leave its internet link's tunnel running until it is stopped.
- Desktop builds are unsigned until signing certificates are added.
