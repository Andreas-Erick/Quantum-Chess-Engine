// Mirrors api/schemas.py — the JSON contract with the engine.

export type Color = "white" | "black";
export type Kind = "pawn" | "knight" | "bishop" | "rook" | "queen" | "king";

export interface PieceInfo {
  square: string;
  symbol: string;
  kind: Kind;
  color: Color;
  probability: number;
}

export interface MeasurementInfo {
  kind: "square" | "path";
  squares: string[];
  probability: number;
  outcome: boolean;
  collapsed: Record<string, boolean>;
}

export interface HistoryEntry {
  notation: string;
  executed: boolean;
  outcomes: boolean[];
}

export interface GameState {
  game_id: string;
  initial_fen: string;
  turn: Color;
  winner: Color | null;
  draw_reason: string | null;
  /** Squares where the mover's king may be that the opponent could capture next move. */
  check: Record<string, number>;
  halfmove_clock: number;
  probabilities: number[];
  pieces: PieceInfo[];
  entanglement_groups: string[][];
  history: HistoryEntry[];
}

export interface MoveResponse {
  move: string;
  executed: boolean;
  captured: string | null;
  measurements: MeasurementInfo[];
  state: GameState;
}

export interface SearchInfo {
  iterations: number;
  elapsed: number;
  top_moves: { move: string; visits: number; value: number }[];
}

export interface AIMoveResponse extends MoveResponse {
  search: SearchInfo;
}

export interface Correlations {
  square: string;
  probability: number;
  if_occupied: Record<string, number>;
  if_empty: Record<string, number>;
}
