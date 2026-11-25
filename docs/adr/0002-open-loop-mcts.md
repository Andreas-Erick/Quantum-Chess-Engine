# ADR-0002: Search with open-loop MCTS, not minimax

- **Status:** Accepted
- **Date:** 2026-10-12
- **Code:** `agent/mcts.py`, `agent/heuristics.py`, `agent/arena.py`

## Context

Every capture of or by an uncertain piece measures the board, and the outcome is random. The
same move can lead to very different positions. A position also has far more legal moves than
in chess: a queen alone can have around 200 possible splits.

The AI has to play reasonably within a few seconds, on the same process that serves the game.

## Options considered

1. **Minimax / alpha-beta with chance nodes (expectimax).** Exact in principle, but every
   measurement adds a chance node, and with hundreds of moves per position the tree is too
   wide to search more than a ply or two. Pruning works poorly under chance nodes.
2. **Closed-loop MCTS** (tree nodes are positions). Each measurement outcome becomes its own
   child, so the tree fragments and statistics spread thin across outcomes that rarely recur.
3. **Open-loop MCTS** (tree nodes are move sequences). Each iteration replays the sequence on
   a fresh copy of the position with newly sampled measurements, so a node's statistics
   average over the quantum dice in proportion to their true probabilities.

## Decision

Option 3, with two additions for the wide move lists:

- **Progressive widening:** a node considers about 0.7·√visits candidates. Captures are
  ordered by expected value, then ordinary and quantum moves are interleaved.
- **Root lookahead:** every root move is first played on a copy and scored one move ahead.

The evaluation weighs material and centrality by the probability that each piece is really
there. Named strength levels (`agent/levels.py`) are just option sets for the same agent.

## Consequences

- One search handles randomness without special cases, and the engine stays the only place
  that knows the rules.
- Every change to the AI is measured, not guessed: `python -m agent.arena` plays two option
  sets against each other. The widening constant moved from 2·√n to 0.7·√n because the arena
  showed an 83% win rate for the narrower setting.
- Replaying from the root on every iteration costs time that a closed-loop tree would save.
  Deep tactics are still out of reach; see *Limitations* in the README.
- An AI search holds the game's lock for seconds, so the WebSocket handler takes that lock
  from a worker thread, never on the event loop (`run_in_threadpool` in `api/server.py`).
