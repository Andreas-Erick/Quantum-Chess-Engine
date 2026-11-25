# ADR-0003: Jointly seeded, commit–reveal dice for online games

- **Status:** Accepted
- **Date:** 2026-10-12
- **Code:** `api/fairness.py`, `desktop/app.py` (`join_game`)

## Context

The desktop app lets one player host a game for a friend. The host's machine runs the server,
and the server rolls the dice for every measurement. A host running modified code could pick
the outcome of every measurement, and in quantum chess that decides captures and games.

There is no neutral server to trust: the point of hosting is that no one has to run one.

## Options considered

1. **Trust the host.** No code, but the host can cheat undetectably.
2. **Each player rolls in turn.** Each side could still choose the outcomes of its own
   measurements.
3. **Commit–reveal with a joint seed.** The server commits to a secret by publishing its
   SHA-256 before the guest joins. The guest then sends a random seed of their own. Roll *n*
   is `sha256(secret ‖ guest_seed ‖ n)`. The secret is revealed when the game ends, and the
   guest replays the game with the same dice.

## Decision

Option 3. `SeededDice` is a counter-based generator built only on SHA-256, so it is trivial to
reimplement elsewhere, unlike a library generator's internal stream. `verify` replays the
recorded game on a fresh engine and reports the first move whose outcome differs.

The desktop app generates and keeps the guest's seed in Python (`join_game`), out of reach of
the host's page that runs in the guest's window. Verification is in the **Game** menu and on
the command line (`quantum-chess-verify`).

## Consequences

- Neither side alone can choose any outcome, and a cheating host is caught after the game.
- A host running modified code can still **peek** at upcoming outcomes during the game, since
  the server must know the seed to roll. Only a neutral server rules that out. `SECURITY.md`
  lists it as a known limitation.
- A guest joining from a plain browser on the host's own page runs the host's code, so it can
  only trust the host. The guarantee holds for the desktop app.
- The guest must keep their own copy of the seed: checking against the game record alone would
  let a server swap in a seed that fits outcomes it chose.
- Replays must be deterministic: the engine must consume the dice in the same order every
  time. `tests/test_fairness.py` replays finished games and checks that tampering is caught.
