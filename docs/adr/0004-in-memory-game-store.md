# ADR-0004: Keep games in memory, in one process

- **Status:** Accepted
- **Date:** 2026-10-12
- **Code:** `api/games.py` (`GameStore`, `Game`), `desktop/app.py`

## Context

The same FastAPI app runs in two places: the Docker image, and in-process inside the desktop
app, where one player hosts a friend. Most games are against the AI or between two friends,
and last minutes. The quantum state lives in NumPy arrays held by Cirq, and an AI search needs
the live engine object, not a serialized copy.

## Options considered

1. **A database or Redis.** Games survive restarts, and several server processes could share
   them. But every move would serialize and rebuild the quantum state, the live feed would need
   a pub/sub channel, and the desktop app would have to ship or require a database.
2. **In-memory, one process, bounded.** A dictionary of live `Game` objects, each with its own
   lock, and a cap on how many are kept.

## Decision

Option 2. `GameStore` holds at most `QC_MAX_GAMES` (500) games in an `OrderedDict` and forgets
the least recently used when a new one is created. Each `Game` has a `threading.Lock` that
every method takes, so moves, AI searches and feed subscriptions never interleave.

The history records every measurement outcome, so a game can always be rebuilt from its JSON
(`QuantumBoard.replay`). That keeps a persistent store possible later without changing the
contract.

## Consequences

- No setup: `docker compose up` or the desktop app is the whole deployment.
- A restart loses every game, online games in progress included. Documented under
  *Limitations* in the README.
- The server can't scale horizontally. Moving to Redis or a database means replacing
  `GameStore` (one class), plus a pub/sub channel for `/ws`.
- The cap bounds memory, but a busy public server could evict a game someone is still
  playing. The desktop app, the main way to host, never comes near the cap.
- Locks are per game, so one long AI search blocks only its own game.
