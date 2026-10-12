"""Sparse quantum register: only squares whose occupancy is uncertain are simulated.

Each chess square maps to a Cirq ``GridQubit(rank, file)``; |1> means occupied. A full
64-qubit state vector (2^64 amplitudes) cannot be stored, so the register holds only the
squares a quantum move has touched, and it stores them as independent *groups*. A group is a
set of squares that may be entangled with each other, with its own state vector, so the
cost is exponential only in the size of the largest group, not in the number of uncertain
squares. Groups are combined when a gate or measurement spans them, and a square is factored
out and handed back to the classical board as soon as its occupancy is certain again.
"""

from __future__ import annotations

from typing import Iterable

import cirq
import numpy as np

from engine.bitboard import file_of, rank_of

EPSILON = 1e-9


def square_qubit(sq: int) -> cirq.GridQubit:
    return cirq.GridQubit(rank_of(sq), file_of(sq))


def qubit_square(qubit: cirq.GridQubit) -> int:
    return qubit.row * 8 + qubit.col


class _Group:
    """A state vector over a list of squares (big-endian: first square = most significant)."""

    def __init__(self, squares: list[int], state: np.ndarray) -> None:
        self.squares = squares
        self.state = state

    def tensor(self) -> np.ndarray:
        return self.state.reshape([2] * len(self.squares))

    def weights(self) -> np.ndarray:
        return np.abs(self.tensor()) ** 2


class QuantumRegister:
    def __init__(self) -> None:
        self._groups: list[_Group] = []
        self._group_of: dict[int, _Group] = {}
        # Every gate and single-square measurement applied, for inspection and visualisation.
        # Path measurements (joint "is this path clear?" projections) are not logged.
        self.circuit = cirq.Circuit()
        self._measurement_count = 0

    def __contains__(self, sq: int) -> bool:
        return sq in self._group_of

    def __len__(self) -> int:
        return len(self._group_of)

    @property
    def squares(self) -> tuple[int, ...]:
        return tuple(sq for group in self._groups for sq in group.squares)

    @property
    def groups(self) -> list[tuple[int, ...]]:
        """The entanglement groups, each a tuple of squares."""
        return [tuple(group.squares) for group in self._groups]

    @property
    def largest_group(self) -> int:
        return max((len(g.squares) for g in self._groups), default=0)

    def add(self, sq: int, occupied: bool) -> None:
        """Bring a classically known square into the simulation as its own group."""
        if sq in self:
            raise ValueError(f"square {sq} is already in the register")
        state = np.array([0, 1] if occupied else [1, 0], dtype=np.complex128)
        group = _Group([sq], state)
        self._groups.append(group)
        self._group_of[sq] = group

    def _combine(self, squares: Iterable[int]) -> _Group:
        """Merge the groups containing ``squares`` into one group (tensor product)."""
        groups: list[_Group] = []
        for sq in squares:
            if sq not in self:
                raise ValueError(f"square {sq} is not in the register")
            group = self._group_of[sq]
            if all(group is not g for g in groups):
                groups.append(group)
        combined = groups[0]
        for group in groups[1:]:
            combined.state = np.kron(combined.state, group.state)
            combined.squares.extend(group.squares)
            for sq in group.squares:
                self._group_of[sq] = combined
            self._groups.remove(group)
        return combined

    def apply(self, operations: Iterable[cirq.Operation]) -> None:
        circuit = cirq.Circuit(operations)
        group = self._combine(sorted(qubit_square(q) for q in circuit.all_qubits()))
        group.state = cirq.final_state_vector(
            circuit,
            initial_state=group.state,
            qubit_order=[square_qubit(sq) for sq in group.squares],
            dtype=np.complex128,
        )
        self.circuit += circuit

    def probability(self, sq: int) -> float:
        """Probability that ``sq`` is occupied."""
        group = self._group_of[sq]
        axis = group.squares.index(sq)
        return float(group.weights().take(1, axis=axis).sum())

    def _all_empty_mask(self, group: _Group, squares: list[int]) -> np.ndarray:
        """Boolean tensor: True on basis states where every square in ``squares`` is empty."""
        mask = np.ones([2] * len(group.squares), dtype=bool)
        for sq in squares:
            axis = group.squares.index(sq)
            index = [slice(None)] * mask.ndim
            index[axis] = 1
            mask[tuple(index)] = False
        return mask

    def probability_all_empty(self, squares: list[int]) -> float:
        """Probability that every square in ``squares`` is empty (e.g. a sliding path)."""
        probability = 1.0
        by_group: dict[int, tuple[_Group, list[int]]] = {}
        for sq in squares:
            group = self._group_of[sq]
            by_group.setdefault(id(group), (group, []))[1].append(sq)
        for group, members in by_group.values():
            probability *= float(group.weights()[self._all_empty_mask(group, members)].sum())
        return probability

    def joint_probability(self, assignment: dict[int, bool]) -> float:
        """Probability that each square's occupancy matches ``assignment`` simultaneously."""
        probability = 1.0
        by_group: dict[int, tuple[_Group, dict[int, bool]]] = {}
        for sq, occupied in assignment.items():
            group = self._group_of[sq]
            by_group.setdefault(id(group), (group, {}))[1][sq] = occupied
        for group, members in by_group.values():
            index = [slice(None)] * len(group.squares)
            for sq, occupied in members.items():
                index[group.squares.index(sq)] = int(occupied)
            probability *= float(group.weights()[tuple(index)].sum())
        return probability

    def _project(self, group: _Group, keep: np.ndarray) -> None:
        tensor = np.where(keep, group.tensor(), 0)
        norm = np.linalg.norm(tensor)
        if norm < EPSILON:
            raise ValueError("measurement outcome has zero probability")
        group.state = (tensor / norm).reshape(-1)

    def project(self, sq: int, occupied: bool) -> None:
        """Collapse ``sq`` onto the given outcome and renormalise."""
        group = self._group_of[sq]
        keep = self._all_empty_mask(group, [sq])
        self._project(group, ~keep if occupied else keep)
        self._measurement_count += 1
        self.circuit.append(cirq.measure(square_qubit(sq), key=f"m{self._measurement_count}"))

    def project_all_empty(self, squares: list[int], all_empty: bool) -> None:
        """Project onto "every square in ``squares`` is empty" (or its complement)."""
        group = self._combine(squares)
        keep = self._all_empty_mask(group, squares)
        self._project(group, keep if all_empty else ~keep)

    def release_definite(self) -> dict[int, bool]:
        """Factor out every square whose occupancy is now certain.

        Returns ``{square: occupied}`` for each released square. Because squares can be
        entangled, collapsing one square may make several others definite at once.
        """
        released: dict[int, bool] = {}
        for group in list(self._groups):
            changed = True
            while changed and group.squares:
                changed = False
                for sq in list(group.squares):
                    p = self.probability(sq)
                    if EPSILON < p < 1 - EPSILON:
                        continue
                    occupied = p >= 0.5
                    axis = group.squares.index(sq)
                    state = group.tensor().take(int(occupied), axis=axis).reshape(-1)
                    group.state = state / np.linalg.norm(state)
                    group.squares.remove(sq)
                    del self._group_of[sq]
                    released[sq] = occupied
                    changed = True
            if not group.squares:
                self._groups.remove(group)
        return released
