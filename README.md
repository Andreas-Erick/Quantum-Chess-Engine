# Quantum Chess

A chess variant in which pieces can be in **superposition** (split across two squares), become
**entangled** (one piece's position depends on another's), and **collapse** on measurement.
Quantum state is simulated with [Cirq](https://quantumai.google/cirq). The game rules, the API and
the AI agent are separate modules that communicate only through strict JSON schemas.

## Status

| Phase | Scope | State |
|---|---|---|
| 1. Classical foundation | Bitboard move generator, full rules, perft-verified | ✅ done |
| 2. Quantum layer | Cirq integration, split / merge moves, measurement | ✅ done |
| 3. Entanglement | Slide moves through superposed pieces, collapse chains | ✅ done |
| 4. API & AI | FastAPI server, MCTS agent, Docker | ⏳ next |

## Layout

```
engine/
  bitboard.py     # square indexing, precomputed attack tables, ray-based slider attacks
  classical.py    # ClassicalBoard: FEN, legal move generation, make/unmake, game outcomes
  register.py     # sparse register: independent Cirq-simulated groups of uncertain squares
  moves.py        # QuantumMove (jump / split / merge / slide), notation, iSWAP-family gates
  measurement.py  # ProbabilityResolver: Born-rule sampling, collapse, chain reactions
  board.py        # QuantumBoard: rules that tie the classical and quantum layers together
api/              # FastAPI wrapper (Phase 4)
agent/            # MCTS agent (Phase 4)
tests/
  test_classical.py
  test_superposition.py
  test_measurement.py
  test_entanglement.py   # slides, path measurement, A->B->C collapse chains
```

## Classical engine

`ClassicalBoard` implements all of standard chess: castling (including through-check rules),
en passant, under-promotion, pins, checkmate, stalemate, the fifty-move rule, threefold repetition
and insufficient material.

The move generator is checked with **perft**, which counts every leaf of the legal-move tree and
compares it to published reference counts. The suite includes the five standard positions from the
Chess Programming Wiki (for example, start position depth 4 = 197,281 and "Kiwipete" depth 3 =
97,862). A single bug in castling, en passant or pin handling changes these numbers.

```python
from engine.classical import ClassicalBoard

board = ClassicalBoard()
board.play("e2e4")
print(board)
print([m.uci() for m in board.legal_moves()][:5])
```

## Quantum rules

```python
from engine.board import QuantumBoard

board = QuantumBoard()
board.do_move("g1^f3h3")         # split: knight is 50% on f3, 50% on h3
board.do_move("e7e5")
result = board.do_move("f3h3^g1")  # merge: interference puts it back on g1 with certainty
print(board)
print(board.probabilities())     # 64 occupancy probabilities, a1 .. h8
```

| Move | Notation | Unitary |
|---|---|---|
| Jump | `e2e4` | `iSWAP(src, tgt)` |
| Split | `b1^a3c3` | `sqrt(iSWAP)(src, t1)` then `iSWAP(src, t2)` |
| Merge | `a3c3^b1` | inverse of split |
| Slide | `a1a5` through a superposed square | `iSWAP(src, tgt)` controlled on every path square being empty |

* All gates come from the iSWAP family, which **conserves the number of occupied squares**, so a
  unitary can move a piece's probability around but can never create or destroy a piece.
* **Measurement** happens only when a move needs a definite answer: capturing or entering a
  superposed square, or capturing *with* a superposed piece. Outcomes are sampled by the Born
  rule. Collapsing one square makes every square it was correlated with definite too, and the
  `Measurement` event reports that chain reaction.
* If a measurement makes the move impossible (for example, the attacker turns out not to be
  there), the move fails but the turn still passes.
* There is no check. You win by capturing the enemy king, and a superposed king may survive an
  attack. En passant is not supported in quantum play. Pawns cannot split.
* **Slides create entanglement.** A rook moving through a square that holds a knight with 50%
  probability ends up 50% at its destination and 50% where it started, *correlated* with the
  knight. `QuantumBoard.joint_probability` exposes these correlations.
* A capture along an uncertain path first makes a **path measurement**, which answers only "is
  the path clear?". If the answer is "blocked", it does not reveal which piece blocked the path:
  the possible blockers stay in superposition, now entangled with each other.
* **Chain reactions:** a knight on c3 *or* d2, a rook that slid a3→e3 through c3, and a queen
  that slid e1→e5 through e3 form one entangled system. Capturing on c3 collapses all six squares
  at once (`test_capturing_the_root_collapses_the_whole_chain`).
* Relative phase is real: if one half of a split piece moves on its own, a later merge
  recombines it only partially (see `test_merge_with_mismatched_phase_only_partly_recombines`).

### Why not a literal 64-qubit state vector

A full state vector for 64 qubits has 2^64 amplitudes, which no simulator can hold. The board
keeps every square whose occupancy is certain on a classical label array. A square enters the
Cirq simulation (as `GridQubit(rank, file)`) only when a quantum move touches it, and it is
factored back out as soon as its probability returns to exactly 0 or 1.

Uncertain squares are further split into **independent groups**, each with its own state vector.
Two pieces that were split separately and never interacted cost 2^2 + 2^2 amplitudes, not 2^4.
Groups are combined (tensor product) only when a gate or a path measurement spans them, which
happens when pieces actually interact. In random self-play, 25+ squares are uncertain at once while
the largest group stays near 2^19 amplitudes.

## Development

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows; use `source .venv/bin/activate` elsewhere
pip install -r requirements-dev.txt
pytest -q
black --check . && flake8
```
