# ADR-0001: Simulate only uncertain squares, in independent groups

- **Status:** Accepted
- **Date:** 2026-10-12
- **Code:** `engine/register.py`, `engine/board.py`

## Context

A quantum chess position is a superposition of classical boards. The literal model, one qubit
per square, needs a state vector of 2^64 amplitudes, which no machine can store. Most squares
are certain at any moment, though: a piece is known to be there, or the square is known to be
empty. In random self-play 25 or more squares can be uncertain at once, but they rarely all
depend on each other.

The engine also has to stay fast enough for the AI, which replays thousands of positions per
move.

## Options considered

1. **A full state vector over every uncertain square.** Simple, and correct by construction.
   Cost is 2^(uncertain squares), so 25 uncertain squares is already 32M amplitudes per copy,
   and the AI copies the position on every iteration.
2. **A list of classical boards with weights** (a "many worlds" sampler). Cheap to read, but
   it can't represent relative phase, so a split piece whose halves moved separately would
   recombine fully when merged. That is not quantum mechanics, and it is the one effect that
   makes the game more than dice.
3. **Independent entanglement groups.** Each group is its own state vector over the squares
   that may be entangled with each other. A gate or measurement that spans two groups merges
   them (a tensor product). A square whose occupancy becomes exactly 0 or 1 is factored out
   and handed back to the classical board.

## Decision

Option 3. `QuantumRegister` keeps a list of `_Group`s, each a Cirq state vector over a list of
squares. `QuantumBoard` stores labels (which piece would be on a square) separately from the
register, so labels never carry probabilities. `release_definite` runs after every move.

## Consequences

- Cost is exponential in the **largest group**, not in the number of uncertain squares. In
  self-play the largest group stays around 19 qubits while 25+ squares are uncertain.
- Phase is kept, so merges interfere correctly. `tests/test_superposition.py` checks the
  partial recombination.
- Every operation has to find, merge and later split groups, which is more code than a single
  state vector, and the bookkeeping is the riskiest part of the engine. It is tested by
  random-play invariants: probabilities stay in [0, 1] and piece counts are conserved.
- A long chain of slides can still entangle many squares into one group. There is no hard cap
  in the engine; the AI stops a rollout once a group passes 12 qubits
  (`max_group_qubits` in `agent/mcts.py`) instead.
- Factoring a square out needs an exact 0 or 1 (within `EPSILON`). Squares that are only
  *almost* certain stay in the register.
