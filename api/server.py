"""FastAPI server exposing the quantum chess engine and the MCTS agent over JSON.

Run locally with ``uvicorn api.server:app --reload``; interactive docs are at ``/docs``.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from agent.levels import DEFAULT_LEVEL, LEVELS
from api import __version__
from agent.mcts import MCTSAgent, SearchResult
from api.fairness import SeededDice, commitment, new_secret
from api.schemas import (
    AIMoveRequest,
    AIMoveResponse,
    CorrelationsResponse,
    FairnessInfo,
    GameState,
    HistoryEntry,
    InitRequest,
    JoinRequest,
    LegalMovesResponse,
    LevelInfo,
    MeasurementInfo,
    MoveRequest,
    MoveResponse,
    MoveStatsInfo,
    OnlineCreateRequest,
    PieceInfo,
    SearchInfo,
    SeatResponse,
)
from engine.bitboard import COLOR_NAMES, parse_square, square_name
from engine.board import IllegalMoveError, MoveResult, QuantumBoard
from engine.classical import STARTING_FEN
from engine.measurement import PathMeasurement

KIND_NAMES = ("pawn", "knight", "bishop", "rook", "queen", "king")

# The built visualizer (``npm run build`` in ui/). Served at / when present.
UI_DIR = Path(os.environ.get("QC_UI_DIR", Path(__file__).resolve().parent.parent / "ui" / "dist"))
# Games kept in memory at once; the least recently used is forgotten beyond that.
MAX_GAMES = int(os.environ.get("QC_MAX_GAMES", 500))
# Live feeds (/ws) per game: two players and some spectators, but not an unbounded number.
MAX_FEEDS = 16
# Set in the ASGI scope by a wrapper (the desktop app's ``GuestsOnly``) for requests from other
# machines: those may only reach online games, never the host's own games against the AI.
GUEST = "quantum_chess.guest"


@dataclass
class Game:
    board: QuantumBoard
    lock: threading.Lock = field(default_factory=threading.Lock)
    # Online games only: colour -> seat token, or None while the seat is open.
    seats: Optional[dict[str, Optional[str]]] = None
    # Online games only: the server's share of the dice, and the joiner's once they join.
    secret: Optional[str] = None
    guest_seed: Optional[str] = None
    # Live feeds (/ws): each is a queue owned by an event loop. Guarded by ``lock``.
    subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = field(default_factory=list)

    def seat_info(self) -> Optional[dict[str, bool]]:
        if self.seats is None:
            return None
        return {color: token is not None for color, token in self.seats.items()}

    def fairness(self) -> Optional[FairnessInfo]:
        if self.secret is None:
            return None
        return FairnessInfo(
            commitment=commitment(self.secret),
            guest_seed=self.guest_seed,
            # Revealing earlier would let anyone predict the remaining outcomes.
            secret=self.secret if self.board.is_over else None,
        )

    def state(self, game_id: str) -> GameState:
        state = serialize_state(game_id, self.board, self.seat_info())
        state.fairness = self.fairness()
        return state

    def publish(self, message: dict) -> None:
        """Push a message to every live feed. Call with ``lock`` held, so feeds see moves in
        order. Safe from worker threads: delivery is scheduled on each feed's own loop."""
        for loop, queue in self.subscribers:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, message)
            except RuntimeError:  # the loop has closed; the feed is going away
                pass

    def check_turn(self, token: Optional[str]) -> None:
        """In an online game, only the player holding the seat of the side to move may move."""
        if self.seats is None:
            return
        if None in self.seats.values():
            # Also keeps the dice unrolled until the joiner has contributed their seed.
            raise HTTPException(status_code=409, detail="waiting for the other player to join")
        expected = self.seats[COLOR_NAMES[self.board.turn]]
        if expected is None or token is None or not secrets.compare_digest(token, expected):
            raise HTTPException(status_code=403, detail="it is not your turn in this game")


class GameStore:
    """In-memory game registry. Swap for Redis or a database to scale horizontally.

    Holds at most ``max_games``; creating one more forgets the game least recently used, so
    nobody can exhaust the server's memory by creating games."""

    def __init__(self, max_games: int = MAX_GAMES) -> None:
        self._games: OrderedDict[str, Game] = OrderedDict()
        self._lock = threading.Lock()
        self.max_games = max_games

    def create(self, board: QuantumBoard, online: bool = False) -> str:
        game_id = uuid.uuid4().hex[:12]
        game = Game(board)
        if online:
            game.seats = {"white": None, "black": None}
            game.secret = new_secret()
        with self._lock:
            self._games[game_id] = game
            while len(self._games) > self.max_games:
                self._games.popitem(last=False)
        return game_id

    def find(self, game_id: str) -> Optional[Game]:
        with self._lock:
            game = self._games.get(game_id)
            if game is not None:
                self._games.move_to_end(game_id)
            return game

    def get(self, game_id: str, guest: bool = False) -> Game:
        game = self.find(game_id)
        # To a guest, the host's own games don't exist.
        if game is None or (guest and game.seats is None):
            raise HTTPException(status_code=404, detail=f"unknown game {game_id!r}")
        return game


def is_guest(connection: Request | WebSocket) -> bool:
    return bool(connection.scope.get(GUEST))


# --- Serialisation -------------------------------------------------------------------


def serialize_state(
    game_id: str, board: QuantumBoard, seats: Optional[dict[str, bool]] = None
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


def serialize_result(game_id: str, game: Game, result: MoveResult) -> dict:
    measurements = []
    for m in result.measurements:
        is_path = isinstance(m, PathMeasurement)
        measurements.append(
            MeasurementInfo(
                kind="path" if is_path else "square",
                squares=[square_name(s) for s in (m.path if is_path else (m.square,))],
                probability=m.probability,
                outcome=m.clear if is_path else m.occupied,
                collapsed={square_name(s): v for s, v in m.collapsed.items()},
            )
        )
    return dict(
        move=result.move.notation(),
        executed=result.executed,
        captured=result.captured.symbol if result.captured else None,
        measurements=measurements,
        state=game.state(game_id),
    )


def serialize_search(search: SearchResult, limit: int = 5) -> SearchInfo:
    return SearchInfo(
        iterations=search.iterations,
        elapsed=search.elapsed,
        top_moves=[
            MoveStatsInfo(move=s.move.notation(), visits=s.visits, value=s.value)
            for s in search.moves[:limit]
        ],
    )


# --- Application ---------------------------------------------------------------------


def create_app(store: Optional[GameStore] = None, ui_dir: Optional[Path] = UI_DIR) -> FastAPI:
    store = store or GameStore()
    app = FastAPI(
        title="Quantum Chess Engine",
        version=__version__,
        description="Chess with superposition, entanglement and measurement, simulated with Cirq.",
    )

    # The Vite dev server (npm run dev) runs on another port during UI development.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/init", response_model=GameState)
    def init(request: Optional[InitRequest] = None) -> GameState:
        request = request or InitRequest()
        try:
            board = QuantumBoard(
                request.fen or STARTING_FEN, rng=np.random.default_rng(request.seed)
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        game_id = store.create(board)
        return store.get(game_id).state(game_id)

    @app.get("/state", response_model=GameState)
    def state(http: Request, game_id: str = Query(...)) -> GameState:
        game = store.get(game_id, is_guest(http))
        with game.lock:
            return game.state(game_id)

    @app.get("/correlations", response_model=CorrelationsResponse)
    def correlations(
        http: Request, game_id: str = Query(...), square: str = Query(...)
    ) -> CorrelationsResponse:
        game = store.get(game_id, is_guest(http))
        try:
            sq = parse_square(square)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        with game.lock:
            board = game.board

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

    @app.get("/levels", response_model=list[LevelInfo])
    def levels() -> list[LevelInfo]:
        return [
            LevelInfo(
                name=level.name,
                label=level.label,
                description=level.description,
                default=level.name == DEFAULT_LEVEL,
            )
            for level in LEVELS.values()
        ]

    @app.get("/legal_moves", response_model=LegalMovesResponse)
    def legal_moves(http: Request, game_id: str = Query(...)) -> LegalMovesResponse:
        game = store.get(game_id, is_guest(http))
        with game.lock:
            moves = [m.notation() for m in game.board.legal_moves()]
        return LegalMovesResponse(game_id=game_id, moves=moves)

    @app.post("/do_move", response_model=MoveResponse)
    def do_move(request: MoveRequest, http: Request) -> MoveResponse:
        game = store.get(request.game_id, is_guest(http))
        with game.lock:
            if game.board.is_over:
                raise HTTPException(status_code=409, detail="the game is over")
            game.check_turn(request.token)
            try:
                result = game.board.do_move(request.to_notation())
            except (IllegalMoveError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            response = MoveResponse(**serialize_result(request.game_id, game, result))
            game.publish({"type": "move", **response.model_dump(mode="json")})
            return response

    @app.post("/ai_move", response_model=AIMoveResponse)
    def ai_move(request: AIMoveRequest) -> AIMoveResponse:
        game = store.get(request.game_id)
        with game.lock:
            if game.board.is_over:
                raise HTTPException(status_code=409, detail="the game is over")
            if game.seats is not None:
                raise HTTPException(status_code=403, detail="no AI moves in an online game")
            if request.level is not None:
                agent = LEVELS[request.level].agent(seed=request.seed)
            else:
                agent = MCTSAgent(
                    iterations=request.iterations,
                    rollout_depth=request.rollout_depth,
                    time_limit=request.time_limit,
                    seed=request.seed,
                )
            search = agent.search(game.board)
            result = game.board.do_move(search.move)
            response = AIMoveResponse(
                **serialize_result(request.game_id, game, result),
                search=serialize_search(search),
            )
            game.publish({"type": "move", **response.model_dump(mode="json")})
            return response

    # --- Online play: two browsers, one game -------------------------------------------

    @app.post("/online/create", response_model=SeatResponse)
    def online_create(request: Optional[OnlineCreateRequest] = None) -> SeatResponse:
        request = request or OnlineCreateRequest()
        try:
            board = QuantumBoard(request.fen or STARTING_FEN)  # dice are seeded on join
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        color = request.color
        if color == "random":
            color = secrets.choice(["white", "black"])
        game_id = store.create(board, online=True)
        game = store.get(game_id)
        with game.lock:
            token = game.seats[color] = secrets.token_urlsafe(16)
            state = game.state(game_id)
        return SeatResponse(game_id=game_id, color=color, token=token, state=state)

    @app.post("/online/join", response_model=SeatResponse)
    def online_join(request: JoinRequest, http: Request) -> SeatResponse:
        game = store.get(request.game_id, is_guest(http))
        with game.lock:
            if game.seats is None:
                raise HTTPException(status_code=400, detail="this is not an online game")
            open_seats = [color for color, token in game.seats.items() if token is None]
            if not open_seats:
                raise HTTPException(status_code=409, detail="both seats are taken")
            color = open_seats[0]
            token = game.seats[color] = secrets.token_urlsafe(16)
            game.guest_seed = request.seed or secrets.token_hex(32)
            game.board.resolver.rng = SeededDice(game.secret, game.guest_seed)
            state = game.state(request.game_id)
            game.publish({"type": "state", "state": state.model_dump(mode="json")})
        return SeatResponse(game_id=request.game_id, color=color, token=token, state=state)

    @app.websocket("/ws")
    async def live_feed(websocket: WebSocket, game_id: str) -> None:
        """Live updates for one game. Sends ``{"type": "state", "state"}`` on connect and when a
        player joins, and ``{"type": "move", ...MoveResponse}`` after every move. Anything the
        client sends is ignored; it only keeps the connection alive."""
        game = store.find(game_id)
        if game is None or (is_guest(websocket) and game.seats is None):
            await websocket.close(code=4404)
            return
        await websocket.accept()
        queue: asyncio.Queue = asyncio.Queue()
        feed = (asyncio.get_running_loop(), queue)

        def subscribe() -> Optional[dict]:
            # Snapshot and subscribe under the game lock so no move can fall in between.
            with game.lock:
                if len(game.subscribers) >= MAX_FEEDS:
                    return None
                game.subscribers.append(feed)
                return {"type": "state", "state": game.state(game_id).model_dump(mode="json")}

        def unsubscribe() -> None:
            with game.lock:
                game.subscribers.remove(feed)

        # The lock may be held by an AI search for seconds: never take it on the event loop.
        snapshot = await run_in_threadpool(subscribe)
        if snapshot is None:
            await websocket.close(code=4429, reason="too many live feeds for this game")
            return
        queue.put_nowait(snapshot)

        async def pump() -> None:
            while True:
                await websocket.send_json(await queue.get())

        sender = asyncio.create_task(pump())
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            sender.cancel()
            await run_in_threadpool(unsubscribe)

    if ui_dir is not None and ui_dir.is_dir():
        # Mounted last so the API routes above take precedence.
        app.mount("/", StaticFiles(directory=ui_dir, html=True), name="ui")

    return app


app = create_app()
