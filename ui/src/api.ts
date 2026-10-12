import type {
  AIMoveResponse,
  Color,
  Correlations,
  GameState,
  LevelInfo,
  LevelName,
  MoveResponse,
  SeatResponse,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      // keep the status text
    }
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  init: (fen?: string) => post<GameState>("/init", fen ? { fen } : {}),
  state: (gameId: string) => request<GameState>(`/state?game_id=${encodeURIComponent(gameId)}`),
  legalMoves: (gameId: string) =>
    request<{ moves: string[] }>(`/legal_moves?game_id=${encodeURIComponent(gameId)}`).then((r) => r.moves),
  move: (gameId: string, notation: string, token?: string) =>
    post<MoveResponse>("/do_move", { game_id: gameId, notation, token }),
  createOnline: (color: Color | "random") => post<SeatResponse>("/online/create", { color }),
  joinOnline: (gameId: string, seed: string) => post<SeatResponse>("/online/join", { game_id: gameId, seed }),
  aiMove: (gameId: string, level: LevelName) => post<AIMoveResponse>("/ai_move", { game_id: gameId, level }),
  levels: () => request<LevelInfo[]>("/levels"),
  correlations: (gameId: string, square: string) =>
    request<Correlations>(
      `/correlations?game_id=${encodeURIComponent(gameId)}&square=${encodeURIComponent(square)}`,
    ),
};

/** The live-feed WebSocket URL for a game, on the same host that serves the page. */
export function liveUrl(gameId: string): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws?game_id=${encodeURIComponent(gameId)}`;
}
