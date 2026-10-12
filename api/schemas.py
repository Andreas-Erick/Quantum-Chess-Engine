"""Pydantic models: the JSON contract between the engine, clients and the AI agent."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

Color = Literal["white", "black"]
SquareName = str  # "a1" .. "h8"


class InitRequest(BaseModel):
    fen: Optional[str] = Field(None, description="Starting position; standard setup if omitted")
    seed: Optional[int] = Field(None, description="Seed for measurement outcomes")


class MoveRequest(BaseModel):
    """A move either as notation (``e2e4``, ``b1^a3c3``, ``a3c3^b1``) or as structured fields."""

    game_id: str
    notation: Optional[str] = None
    move_type: Literal["jump", "split", "merge"] = "jump"
    source: Optional[SquareName] = None
    source2: Optional[SquareName] = Field(None, description="Second source of a merge")
    target1: Optional[SquareName] = None
    target2: Optional[SquareName] = Field(None, description="Second target of a split")
    promotion: Optional[Literal["q", "r", "b", "n"]] = None

    @model_validator(mode="after")
    def _check_fields(self) -> "MoveRequest":
        if self.notation is not None:
            return self
        required = {
            "jump": ("source", "target1"),
            "split": ("source", "target1", "target2"),
            "merge": ("source", "source2", "target1"),
        }[self.move_type]
        missing = [name for name in required if getattr(self, name) is None]
        if missing:
            raise ValueError(f"{self.move_type} move needs: {', '.join(missing)}")
        return self

    def to_notation(self) -> str:
        if self.notation is not None:
            return self.notation
        if self.move_type == "split":
            return f"{self.source}^{self.target1}{self.target2}"
        if self.move_type == "merge":
            return f"{self.source}{self.source2}^{self.target1}"
        return f"{self.source}{self.target1}{self.promotion or ''}"


LevelName = Literal["easy", "medium", "hard"]


class AIMoveRequest(BaseModel):
    """Pick a ``level``, or tune the search directly (the fields below apply without a level)."""

    game_id: str
    level: Optional[LevelName] = Field(None, description="Named strength; overrides the rest")
    iterations: int = Field(400, ge=1, le=20000)
    rollout_depth: int = Field(6, ge=0, le=40)
    time_limit: Optional[float] = Field(None, gt=0, le=60, description="Seconds")
    seed: Optional[int] = None


class PieceInfo(BaseModel):
    square: SquareName
    symbol: str = Field(description="FEN letter: uppercase white, lowercase black")
    kind: Literal["pawn", "knight", "bishop", "rook", "queen", "king"]
    color: Color
    probability: float


class MeasurementInfo(BaseModel):
    kind: Literal["square", "path"]
    squares: list[SquareName]
    probability: float = Field(description="Prior probability of the event (occupied / clear)")
    outcome: bool
    collapsed: dict[SquareName, bool] = Field(
        description="Squares that became certain, mapped to whether they are occupied"
    )


class HistoryEntry(BaseModel):
    notation: str
    executed: bool
    outcomes: list[bool] = Field(description="Measurement outcomes, enough to replay the game")


class GameState(BaseModel):
    game_id: str
    initial_fen: str
    turn: Color
    winner: Optional[Color]
    draw_reason: Optional[str] = Field(
        None, description='Why the game was drawn ("fifty-move rule", "insufficient material")'
    )
    check: dict[SquareName, float] = Field(
        default_factory=dict,
        description="Squares where the mover's king may be that the opponent could capture next "
        "move, mapped to the king's probability of being there",
    )
    halfmove_clock: int = Field(0, description="Plies since a pawn move, capture or measurement")
    probabilities: list[float] = Field(description="64 occupancy probabilities, a1..h8")
    pieces: list[PieceInfo]
    entanglement_groups: list[list[SquareName]]
    history: list[HistoryEntry]


class MoveResponse(BaseModel):
    move: str
    executed: bool
    captured: Optional[str] = Field(None, description="FEN letter of the captured piece")
    measurements: list[MeasurementInfo]
    state: GameState


class MoveStatsInfo(BaseModel):
    move: str
    visits: int
    value: float


class SearchInfo(BaseModel):
    iterations: int
    elapsed: float
    top_moves: list[MoveStatsInfo]


class AIMoveResponse(MoveResponse):
    search: SearchInfo


class CorrelationsResponse(BaseModel):
    """How the rest of a square's entanglement group depends on that square."""

    square: SquareName
    probability: float
    if_occupied: dict[SquareName, float] = Field(
        description="Occupancy of each entangled square, given this square is occupied"
    )
    if_empty: dict[SquareName, float] = Field(
        description="Occupancy of each entangled square, given this square is empty"
    )


class LevelInfo(BaseModel):
    name: LevelName
    label: str
    description: str
    default: bool


class LegalMovesResponse(BaseModel):
    game_id: str
    moves: list[str]
