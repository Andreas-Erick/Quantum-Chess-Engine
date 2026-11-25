# Architecture decision records

Short records of the decisions that shaped the project: the problem, the options weighed, what
was chosen and what it costs. [architecture.md](../architecture.md) describes how the code
works today; these say why.

- [0001: Simulate only uncertain squares, in independent groups](0001-sparse-grouped-register.md)
- [0002: Search with open-loop MCTS, not minimax](0002-open-loop-mcts.md)
- [0003: Jointly seeded, commit–reveal dice for online games](0003-commit-reveal-dice.md)
- [0004: Keep games in memory, in one process](0004-in-memory-game-store.md)

To record a new decision, copy the newest record, give it the next number, and set its status
to *Proposed* until it is merged. A decision that replaces an older one marks the older record
*Superseded by ADR-000N* rather than deleting it.
