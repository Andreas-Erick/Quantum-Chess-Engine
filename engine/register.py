"""Sparse quantum register: only squares whose occupancy is uncertain are simulated.

Each chess square maps to a Cirq ``GridQubit(rank, file)``; |1> means occupied. A full
64-qubit state vector (2^64 amplitudes) cannot be stored, so the register holds only the
squares a quantum move has touched. When a square's occupancy becomes certain again
(probability 0 or 1), it is factored out of the state and handed back to the classical board.
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


class QuantumRegister:
    """State vector over the currently uncertain squares, in insertion order."""

    def __init__(self) -> None:
        self._squares: list[int] = []
        self._state = np.ones(1, dtype=np.complex128)
        # Every gate and measurement ever applied, for inspection and visualisation.
        self.circuit = cirq.Circuit()
        self._measurement_count = 0

    def __contains__(self, sq: int) -> bool:
        return sq in self._squares

    def __len__(self) -> int:
        return len(self._squares)

    @property
    def squares(self) -> tuple[int, ...]:
        return tuple(self._squares)

    @property
    def qubits(self) -> list[cirq.GridQubit]:
        return [square_qubit(sq) for sq in self._squares]

    @property
    def state_vector(self) -> np.ndarray:
        return self._state.copy()

    def add(self, sq: int, occupied: bool) -> None:
        """Bring a classically known square into the simulation."""
        if sq in self:
            raise ValueError(f"square {sq} is already in the register")
        basis = np.array([0, 1] if occupied else [1, 0], dtype=np.complex128)
        self._state = np.kron(self._state, basis)
        self._squares.append(sq)

    def apply(self, operations: Iterable[cirq.Operation]) -> None:
        circuit = cirq.Circuit(operations)
        missing = {qubit_square(q) for q in circuit.all_qubits()} - set(self._squares)
        if missing:
            raise ValueError(f"squares {sorted(missing)} are not in the register")
        self._state = cirq.final_state_vector(
            circuit,
            initial_state=self._state,
            qubit_order=self.qubits,
            dtype=np.complex128,
        )
        self.circuit += circuit

    def _tensor(self) -> np.ndarray:
        return self._state.reshape([2] * len(self._squares))

    def probability(self, sq: int) -> float:
        """Probability that ``sq`` is occupied."""
        axis = self._squares.index(sq)
        weights = np.abs(self._tensor()) ** 2
        return float(weights.take(1, axis=axis).sum())

    def project(self, sq: int, occupied: bool) -> None:
        """Collapse ``sq`` onto the given outcome and renormalise."""
        axis = self._squares.index(sq)
        tensor = self._tensor().copy()
        index = [slice(None)] * tensor.ndim
        index[axis] = 0 if occupied else 1
        tensor[tuple(index)] = 0
        norm = np.linalg.norm(tensor)
        if norm < EPSILON:
            raise ValueError(f"outcome occupied={occupied} has zero probability")
        self._state = (tensor / norm).reshape(-1)
        self._measurement_count += 1
        self.circuit.append(cirq.measure(square_qubit(sq), key=f"m{self._measurement_count}"))

    def release_definite(self) -> dict[int, bool]:
        """Factor out every square whose occupancy is now certain.

        Returns ``{square: occupied}`` for each released square. Because squares can be
        entangled, collapsing one square may make several others definite at once.
        """
        released: dict[int, bool] = {}
        changed = True
        while changed:
            changed = False
            for sq in list(self._squares):
                p = self.probability(sq)
                if EPSILON < p < 1 - EPSILON:
                    continue
                occupied = p >= 0.5
                axis = self._squares.index(sq)
                state = self._tensor().take(int(occupied), axis=axis).reshape(-1)
                self._state = state / np.linalg.norm(state)
                self._squares.remove(sq)
                released[sq] = occupied
                changed = True
        return released
