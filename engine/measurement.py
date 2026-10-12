"""Measurement: turning quantum probabilities back into classical facts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

import numpy as np

from engine.register import QuantumRegister


class RandomSource(Protocol):
    def random(self) -> float: ...


@dataclass(frozen=True)
class Measurement:
    square: int
    probability: float  # probability the square was occupied, just before measuring
    occupied: bool  # the observed outcome
    # Every square that became certain as a result, including the measured one.
    # More than one entry means entanglement caused a chain reaction.
    collapsed: dict[int, bool] = field(default_factory=dict)


class ProbabilityResolver:
    """Samples measurement outcomes according to the Born rule."""

    def __init__(self, rng: Optional[RandomSource] = None) -> None:
        self.rng = rng if rng is not None else np.random.default_rng()

    def measure(self, register: QuantumRegister, sq: int) -> Measurement:
        p = register.probability(sq)
        occupied = self.rng.random() < p
        register.project(sq, occupied)
        collapsed = register.release_definite()
        return Measurement(sq, p, occupied, collapsed)
