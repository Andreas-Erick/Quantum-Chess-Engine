"""Named AI strength levels, shared by the API, the UI and the command-line client.

Each level is a set of :class:`~agent.mcts.MCTSAgent` options. Measured in the arena
(``agent/arena.py``): medium beats easy 92% of the time (96 games) and hard beats medium 74%
(72 games).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from agent.mcts import MCTSAgent


@dataclass(frozen=True)
class Level:
    name: str
    label: str
    description: str
    options: dict = field(default_factory=dict)

    def agent(self, seed: Optional[int] = None) -> MCTSAgent:
        return MCTSAgent(seed=seed, **self.options)


LEVELS: dict[str, Level] = {
    level.name: level
    for level in (
        Level(
            "easy",
            "Easy",
            "Short search without lookahead: takes free pieces, but often misses threats.",
            {"iterations": 40, "root_lookahead": False},
        ),
        Level(
            "medium",
            "Medium",
            "Looks one move ahead and searches a few hundred lines.",
            {"iterations": 250},
        ),
        Level(
            "hard",
            "Hard",
            "Searches about five times longer than medium.",
            {"iterations": 1200, "time_limit": 5.0},
        ),
    )
}

DEFAULT_LEVEL = "medium"
