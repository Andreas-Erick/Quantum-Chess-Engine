"""Games held by the server: playing moves, online seats, jointly seeded dice and live feeds.

A :class:`Game` owns everything about one game behind a small interface, and enforces its rules
itself: moves wait until both online seats are taken, only the side to move may move, the dice
are seeded when the friend joins, and every live feed sees every change in order. It raises a
:class:`GameError` for anything a client got wrong; the HTTP routes in api/server.py only look
games up, call one method and turn those errors into status codes.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import threading
import uuid
from collections import OrderedDict
from typing import Literal, Optional

from agent.mcts import MCTSAgent, SearchResult
from api.fairness import SeededDice, commitment, new_secret
from api.schemas import (
    AIMoveResponse,
    Color,
    CorrelationsResponse,
    FairnessInfo,
    GameState,
    HistoryEntry,
    KindName,
    MeasurementInfo,
    MoveResponse,
    MoveStatsInfo,
    PieceInfo,
    SearchInfo,
    SeatResponse,
)
from engine.bitboard import COLOR_NAMES, parse_square, square_name
from engine.board import IllegalMoveError, MoveResult, QuantumBoard
from engine.measurement import PathMeasurement

KIND_NAMES: tuple[KindName, ...] = ("pawn", "knight", "bishop", "rook", "queen", "king")
# Live feeds per game: two players and some spectators, but not an unbounded number.
MAX_FEEDS = 16

# A live feed: a queue owned by an event loop, which receives every message for the game.
Feed = tuple[asyncio.AbstractEventLoop, asyncio.Queue]


# --- Errors ---------------------------------------------------------------------------


class GameError(Exception):
    """Something a client asked for that the game refuses. ``status`` is the HTTP status."""

    status = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class UnknownGame(GameError):
    status = 404


class GameOver(GameError):
    status = 409


class WaitingForOpponent(GameError):
    status = 409


class NotYourTurn(GameError):
    status = 403


class SeatsTaken(GameError):
    status = 409


class NotOnline(GameError):
    status = 400


class NoAiOnline(GameError):
    status = 403


class BadMove(GameError):
    status = 400


# --- Games ----------------------------------------------------------------------------


class Game:
    """One game. Thread-safe: every method holds the game's lock, so moves, seats and feed
    messages happen in one order. An AI move holds it for the whole search (seconds), so never
    call a method from an event loop; use a worker thread.

    An *online* game has two seats, white and black, each claimed with a secret token, and
    dice seeded by both players (see api/fairness.py). A local game has neither."""

    def __init__(self, game_id: str, board: QuantumBoard, online: bool = False) -> None:
        self.id = game_id
        self._board = board
        self._lock = threading.Lock()
        # Online games only: colour -> seat token, or None while the seat is open.
        self._seats: Optional[dict[Color, Optional[str]]] = (
            {"white": None, "black": None} if online else None
        )
        # Online games only: the server's share of the dice, and the joiner's once they join.
        self._secret: Optional[str] = new_secret() if online else None
        self._guest_seed: Optional[str] = None
        self._feeds: list[Feed] = []

    @property
    def online(self) -> bool:
        return self._seats is not None

    @property
    def feed_count(self) -> int:
        return len(self._feeds)

    # --- Reading ---------------------------------------------------------------------

    def state(self) -> GameState:
        with self._lock:
            return self._state()

    def legal_moves(self) -> list[str]:
        with self._lock:
            return [m.notation() for m in self._board.legal_moves()]

    def correlations(self, square: str) -> CorrelationsResponse:
        """How the squares entangled with ``square`` depend on its occupancy."""
        try:
            sq = parse_square(square)
        except ValueError as exc:
            raise GameError(str(exc)) from exc
        with self._lock:
            board = self._board

            def named(values: dict[int, float]) -> dict[str, float]:
                return {square_name(s): p for s, p in values.items()}

            probability = board.probability(sq)
            return CorrelationsResponse(
                square=square,
                probability=probability,
                if_occupied=named(board.conditional_probabilities(sq, True)) if probability else {},
                if_empty=(
                    named(board.conditional_probabilities(sq, False)) if probability < 1 else {}
                ),
            )

    # --- Playing ---------------------------------------------------------------------

    def play(self, notation: str, token: Optional[str] = None) -> MoveResponse:
        """Play a move. In an online game ``token`` must be the seat of the side to move."""
        with self._lock:
            self._check_playable()
            self._check_turn(token)
            try:
                result = self._board.do_move(notation)
            except (IllegalMoveError, ValueError) as exc:
                raise BadMove(str(exc)) from exc
            response = MoveResponse(**self._result(result))
            self._publish({"type": "move", **response.model_dump(mode="json")})
            return response

    def play_ai(self, agent: MCTSAgent) -> AIMoveResponse:
        """Let ``agent`` choose and play the side to move's move. Local games only."""
        with self._lock:
            self._check_playable()
            if self.online:
                raise NoAiOnline("no AI moves in an online game")
            search = agent.search(self._board)
            result = self._board.do_move(search.move)
            response = AIMoveResponse(**self._result(result), search=serialize_search(search))
            self._publish({"type": "move", **response.model_dump(mode="json")})
            return response

    # --- Seats -----------------------------------------------------------------------

    def seat_host(self, color: Color) -> SeatResponse:
        """Claim ``color`` for the player who created this online game."""
        with self._lock:
            if self._seats is None:
                raise NotOnline("this is not an online game")
            if self._seats[color] is not None:
                raise SeatsTaken(f"the {color} seat is taken")
            token = self._seats[color] = secrets.token_urlsafe(16)
            return SeatResponse(game_id=self.id, color=color, token=token, state=self._state())

    def join(self, seed: Optional[str] = None) -> SeatResponse:
        """Take the open seat, contributing ``seed`` (or a random one) to the dice. From then
        on, every measurement is rolled by the dice both players seeded."""
        with self._lock:
            if self._seats is None or self._secret is None:
                raise NotOnline("this is not an online game")
            open_seats = [color for color, token in self._seats.items() if token is None]
            if not open_seats:
                raise SeatsTaken("both seats are taken")
            color = open_seats[0]
            token = self._seats[color] = secrets.token_urlsafe(16)
            self._guest_seed = seed or secrets.token_hex(32)
            self._board.reseed(SeededDice(self._secret, self._guest_seed))
            state = self._state()
            self._publish({"type": "state", "state": state.model_dump(mode="json")})
            return SeatResponse(game_id=self.id, color=color, token=token, state=state)

    # --- Live feeds ------------------------------------------------------------------

    def subscribe(self, feed: Feed) -> Optional[dict]:
        """Start sending this game's messages to ``feed``. Returns the first message, a
        ``state`` snapshot taken so that no move falls in between, or None when the game
        already has :data:`MAX_FEEDS` feeds."""
        with self._lock:
            if len(self._feeds) >= MAX_FEEDS:
                return None
            self._feeds.append(feed)
            return {"type": "state", "state": self._state().model_dump(mode="json")}

    def unsubscribe(self, feed: Feed) -> None:
        with self._lock:
            self._feeds.remove(feed)

    # --- Inside the lock -------------------------------------------------------------

    def _state(self) -> GameState:
        seats = None
        if self._seats is not None:
            seats = {color: token is not None for color, token in self._seats.items()}
        state = serialize_state(self.id, self._board, seats)
        if self._secret is not None:
            state.fairness = FairnessInfo(
                commitment=commitment(self._secret),
                guest_seed=self._guest_seed,
                # Revealing earlier would let anyone predict the remaining outcomes.
                secret=self._secret if self._board.is_over else None,
            )
        return state

    def _check_playable(self) -> None:
        if self._board.is_over:
            raise GameOver("the game is over")

    def _check_turn(self, token: Optional[str]) -> None:
        """In an online game, only the player holding the seat of the side to move may move."""
        if self._seats is None:
            return
        if None in self._seats.values():
            # Also keeps the dice unrolled until the joiner has contributed their seed.
            raise WaitingForOpponent("waiting for the other player to join")
        expected = self._seats[COLOR_NAMES[self._board.turn]]
        if expected is None or token is None or not secrets.compare_digest(token, expected):
            raise NotYourTurn("it is not your turn in this game")

    def _publish(self, message: dict) -> None:
        """Push a message to every live feed. Safe from worker threads: delivery is scheduled
        on each feed's own loop."""
        for loop, queue in self._feeds:
            # RuntimeError: the loop has closed, and the feed is going away.
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(queue.put_nowait, message)

    def _result(self, result: MoveResult) -> dict:
        return {**serialize_result(result), "state": self._state()}


class GameStore:
    """In-memory game registry. Swap for Redis or a database to scale horizontally.

    Holds at most ``max_games``; creating one more forgets the game least recently used, so
    nobody can exhaust the server's memory by creating games."""

    def __init__(self, max_games: int = 500) -> None:
        self._games: OrderedDict[str, Game] = OrderedDict()
        self._lock = threading.Lock()
        self.max_games = max_games

    def create(self, board: QuantumBoard, online: bool = False) -> Game:
        game = Game(uuid.uuid4().hex[:12], board, online)
        with self._lock:
            self._games[game.id] = game
            while len(self._games) > self.max_games:
                self._games.popitem(last=False)
        return game

    def get(self, game_id: str, guest: bool = False) -> Game:
        """The game, unless it is unknown, or a guest asks for one of the host's local games:
        guests (other machines, while the desktop app hosts) only see online games."""
        with self._lock:
            game = self._games.get(game_id)
            if game is not None:
                self._games.move_to_end(game_id)
        if game is None or (guest and not game.online):
            raise UnknownGame(f"unknown game {game_id!r}")
        return game


# --- Serialisation -------------------------------------------------------------------


def serialize_state(
    game_id: str, board: QuantumBoard, seats: Optional[dict[Color, bool]] = None
) -> GameState:
    pieces = [
        PieceInfo(
            square=square_name(sq),
            symbol=piece.symbol,
            kind=KIND_NAMES[piece.kind],
            color=COLOR_NAMES[piece.color],
            probability=board.probability(sq),
        )
        for sq, piece in enumerate(board.labels)
        if piece is not None
    ]
    return GameState(
        game_id=game_id,
        initial_fen=board.initial_fen,
        turn=COLOR_NAMES[board.turn],
        winner=COLOR_NAMES[board.winner] if board.winner is not None else None,
        draw_reason=board.draw_reason,
        check={square_name(sq): p for sq, p in board.king_threats().items()},
        halfmove_clock=board.halfmove_clock,
        probabilities=board.probabilities(),
        pieces=pieces,
        entanglement_groups=[[square_name(s) for s in g] for g in board.register.groups],
        history=[
            HistoryEntry(notation=r.move.notation(), executed=r.executed, outcomes=r.outcomes)
            for r in board.history
        ],
        seats=seats,
    )


def serialize_result(result: MoveResult) -> dict:
    """A move's result, as the fields of :class:`MoveResponse` other than ``state``."""
    measurements = []
    for m in result.measurements:
        kind: Literal["path", "square"]
        if isinstance(m, PathMeasurement):
            kind, squares, outcome = "path", m.path, m.clear
        else:
            kind, squares, outcome = "square", (m.square,), m.occupied
        measurements.append(
            MeasurementInfo(
                kind=kind,
                squares=[square_name(s) for s in squares],
                probability=m.probability,
                outcome=outcome,
                collapsed={square_name(s): v for s, v in m.collapsed.items()},
            )
        )
    return {
        "move": result.move.notation(),
        "executed": result.executed,
        "captured": result.captured.symbol if result.captured else None,
        "measurements": measurements,
    }


def serialize_search(search: SearchResult, limit: int = 5) -> SearchInfo:
    return SearchInfo(
        iterations=search.iterations,
        elapsed=search.elapsed,
        top_moves=[
            MoveStatsInfo(move=s.move.notation(), visits=s.visits, value=s.value)
            for s in search.moves[:limit]
        ],
    )
