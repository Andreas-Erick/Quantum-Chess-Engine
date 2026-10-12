"""Measurement: turning quantum probabilities back into classical facts."""

from __future__ import annotations

from collections import deque
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


@dataclass(frozen=True)
class PathMeasurement:
    """A joint measurement of "is every square on this path empty?".

    Only the question asked is answered: if the path is blocked, the individual squares stay
    uncertain (now correlated with each other) unless the outcome pins them down.
    """

    path: tuple[int, ...]
    probability: float  # probability the path was clear, just before measuring
    clear: bool  # the observed outcome
    collapsed: dict[int, bool] = field(default_factory=dict)


class ProbabilityResolver:
    """Samples measurement outcomes according to the Born rule."""

    def __init__(self, rng: Optional[RandomSource] = None) -> None:
        self.rng = rng if rng is not None else np.random.default_rng()
        # Outcomes to use instead of sampling, consumed in order. Used to replay a recorded
        # game exactly (see QuantumBoard.replay).
        self.forced: deque[bool] = deque()

    def _outcome(self, probability: float) -> bool:
        if not self.forced:
            return self.rng.random() < probability
        outcome = self.forced.popleft()
        if (outcome and probability <= 0) or (not outcome and probability >= 1):
            raise ValueError("forced measurement outcome is impossible in this position")
        return outcome

    def measure(self, register: QuantumRegister, sq: int) -> Measurement:
        p = register.probability(sq)
        occupied = self._outcome(p)
        register.project(sq, occupied)
        collapsed = register.release_definite()
        return Measurement(sq, p, occupied, collapsed)

    def measure_path(self, register: QuantumRegister, path: list[int]) -> PathMeasurement:
        p = register.probability_all_empty(path)
        clear = self._outcome(p)
        register.project_all_empty(path, clear)
        collapsed = register.release_definite()
        return PathMeasurement(tuple(path), p, clear, collapsed)
