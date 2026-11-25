"""FastAPI server exposing the quantum chess engine and the MCTS agent over JSON.

Run locally with ``uvicorn api.server:app --reload``; interactive docs are at ``/docs``.

The routes are thin: they look a game up, call one method of :class:`api.games.Game`, and turn
its :class:`api.games.GameError` into a status code. The rules of a game live there.
"""

from __future__ import annotations

import asyncio
import os
import secrets
from pathlib import Path
from typing import Any, Optional

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from agent.levels import DEFAULT_LEVEL, LEVELS
from agent.mcts import MCTSAgent
from api import __version__
from api.games import MAX_FEEDS, GameError, GameStore, UnknownGame
from api.schemas import (
    AIMoveRequest,
    AIMoveResponse,
    Color,
    CorrelationsResponse,
    GameState,
    InitRequest,
    JoinRequest,
    LegalMovesResponse,
    LevelInfo,
    MoveRequest,
    MoveResponse,
    OnlineCreateRequest,
    SeatResponse,
)
from engine.bitboard import COLOR_NAMES
from engine.board import QuantumBoard
from engine.classical import STARTING_FEN

__all__ = ["GUEST", "MAX_FEEDS", "GameStore", "app", "create_app", "host_only", "is_guest"]

# The built visualizer (``npm run build`` in ui/). Served at / when present.
UI_DIR = Path(os.environ.get("QC_UI_DIR", Path(__file__).resolve().parent.parent / "ui" / "dist"))
# Games kept in memory at once; the least recently used is forgotten beyond that.
MAX_GAMES = int(os.environ.get("QC_MAX_GAMES", 500))

# Set in the ASGI scope by a wrapper (the desktop app's ``GuestsOnly``) for requests from other
# machines. Guests may only reach online games, never the host's own games against the AI, and
# may not call the routes that depend on ``host_only``.
GUEST = "quantum_chess.guest"
HOST_ONLY_DETAIL = "Only the host can start games here. Ask them for an invite link."


def is_guest(connection: Request | WebSocket) -> bool:
    return bool(connection.scope.get(GUEST))


def host_only(http: Request) -> None:
    """A route dependency for what only the host may do: anything that creates a game or runs
    an AI search. Anyone who can reach a hosting listener could otherwise make the host's
    computer spend memory and minutes of CPU per request."""
    if is_guest(http):
        raise HTTPException(status_code=403, detail=HOST_ONLY_DETAIL)


class _HideFromGuests:
    """Refuses guests the given paths: the API docs, which FastAPI serves outside any route."""

    def __init__(self, app: Any, paths: frozenset[str]) -> None:
        self.app = app
        self.paths = paths

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope.get(GUEST) and scope["path"].rstrip("/") in self.paths:
            response = JSONResponse({"detail": HOST_ONLY_DETAIL}, status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_app(store: Optional[GameStore] = None, ui_dir: Optional[Path] = UI_DIR) -> FastAPI:
    store = store or GameStore(MAX_GAMES)
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
    docs = (app.docs_url, app.swagger_ui_oauth2_redirect_url, app.redoc_url, app.openapi_url)
    app.add_middleware(_HideFromGuests, paths=frozenset(path for path in docs if path))

    @app.exception_handler(GameError)
    async def game_error(_: Request, exc: GameError) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/init", response_model=GameState, dependencies=[Depends(host_only)])
    def init(request: Optional[InitRequest] = None) -> GameState:
        request = request or InitRequest()
        try:
            board = QuantumBoard(
                request.fen or STARTING_FEN, rng=np.random.default_rng(request.seed)
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return store.create(board).state()

    @app.get("/state", response_model=GameState)
    def state(http: Request, game_id: str = Query(...)) -> GameState:
        return store.get(game_id, is_guest(http)).state()

    @app.get("/correlations", response_model=CorrelationsResponse)
    def correlations(
        http: Request, game_id: str = Query(...), square: str = Query(...)
    ) -> CorrelationsResponse:
        return store.get(game_id, is_guest(http)).correlations(square)

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
        moves = store.get(game_id, is_guest(http)).legal_moves()
        return LegalMovesResponse(game_id=game_id, moves=moves)

    @app.post("/do_move", response_model=MoveResponse)
    def do_move(request: MoveRequest, http: Request) -> MoveResponse:
        game = store.get(request.game_id, is_guest(http))
        return game.play(request.to_notation(), request.token)

    @app.post("/ai_move", response_model=AIMoveResponse, dependencies=[Depends(host_only)])
    def ai_move(request: AIMoveRequest, http: Request) -> AIMoveResponse:
        game = store.get(request.game_id, is_guest(http))
        if request.level is not None:
            agent = LEVELS[request.level].agent(seed=request.seed)
        else:
            agent = MCTSAgent(
                iterations=request.iterations,
                rollout_depth=request.rollout_depth,
                time_limit=request.time_limit,
                seed=request.seed,
            )
        return game.play_ai(agent)

    # --- Online play: two browsers, one game -------------------------------------------

    @app.post("/online/create", response_model=SeatResponse, dependencies=[Depends(host_only)])
    def online_create(request: Optional[OnlineCreateRequest] = None) -> SeatResponse:
        request = request or OnlineCreateRequest()
        try:
            board = QuantumBoard(request.fen or STARTING_FEN)  # dice are seeded on join
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        color: Color = secrets.choice(COLOR_NAMES) if request.color == "random" else request.color
        return store.create(board, online=True).seat_host(color)

    @app.post("/online/join", response_model=SeatResponse)
    def online_join(request: JoinRequest, http: Request) -> SeatResponse:
        return store.get(request.game_id, is_guest(http)).join(request.seed)

    @app.websocket("/ws")
    async def live_feed(websocket: WebSocket, game_id: str) -> None:
        """Live updates for one game. Sends ``{"type": "state", "state"}`` on connect and when a
        player joins, and ``{"type": "move", ...MoveResponse}`` after every move. Anything the
        client sends is ignored; it only keeps the connection alive."""
        try:
            game = store.get(game_id, is_guest(websocket))
        except UnknownGame:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        queue: asyncio.Queue = asyncio.Queue()
        feed = (asyncio.get_running_loop(), queue)

        # The game's lock may be held by an AI search for seconds: never wait for it on the
        # event loop.
        snapshot = await run_in_threadpool(game.subscribe, feed)
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
            await run_in_threadpool(game.unsubscribe, feed)

    if ui_dir is not None and ui_dir.is_dir():
        # Mounted last so the API routes above take precedence.
        app.mount("/", StaticFiles(directory=ui_dir, html=True), name="ui")

    return app


app = create_app()
