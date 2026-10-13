import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { LogEntry } from "../components/MoveLog";
import { type ParsedMove, parseMove } from "../moves";
import { storage } from "../storage";
import type { Correlations, GameState, LiveMessage, MoveResponse, Seat } from "../types";

export const isOver = (state: GameState) => !!state.winner || !!state.draw_reason;
// Errors from fetch are Errors; errors from the desktop bridge are plain { message } objects.
export const message = (e: unknown) =>
  String(e && typeof e === "object" && "message" in e ? (e as { message: unknown }).message : e);

/** Keep the address bar pointing at an online game, so a reload reopens it. */
export function setUrlGame(gameId: string | null) {
  window.history.replaceState(null, "", gameId ? `?game=${encodeURIComponent(gameId)}` : window.location.pathname);
}

export function entriesFromHistory(state: GameState): LogEntry[] {
  return state.history.map((h, i) => ({
    ply: i,
    color: (i % 2 === 0) === state.initial_fen.split(" ")[1].startsWith("w") ? "white" : "black",
    notation: h.notation,
    executed: h.executed,
    captured: null,
    measurements: null,
    outcomes: h.outcomes,
  }));
}

export type Game = ReturnType<typeof useGame>;

/**
 * The game on screen: its state, move log, legal moves and selection, plus the plumbing the
 * other hooks share (`run` for busy/error handling, `showGame` and `applyResponse`).
 */
export function useGame() {
  const [state, setState] = useState<GameState | null>(null);
  const [legal, setLegal] = useState<ParsedMove[]>([]);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [flipped, setFlipped] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [flashing, setFlashing] = useState<Set<string>>(new Set());
  const [correlations, setCorrelations] = useState<Correlations | null>(null);
  const [seat, setSeat] = useState<Seat | null>(null);
  const hoverToken = useRef(0);
  // Plies already shown. Updated synchronously, so a move that arrives twice (as the HTTP
  // response and on the live feed) is applied once.
  const plies = useRef(0);

  const gameId = state?.game_id;
  const online = !!state?.seats;

  const showGame = useCallback((s: GameState, entries: LogEntry[]) => {
    const held = s.seats ? storage.seat(s.game_id) : null;
    plies.current = s.history.length;
    setState(s);
    setLog(entries);
    setPicked([]);
    setCorrelations(null);
    setSeat(held);
    if (held) setFlipped(held.color === "black");
  }, []);

  const run = useCallback(async (task: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await task();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }, []);

  const newGame = useCallback(
    () =>
      run(async () => {
        const fresh = await api.init();
        storage.setGameId(fresh.game_id);
        setUrlGame(null);
        setNotice(null);
        setFlipped(false);
        showGame(fresh, []);
      }),
    [run, showGame],
  );

  const resume = useCallback(
    async (id: string) => {
      try {
        const s = await api.state(id);
        storage.setGameId(id);
        setUrlGame(s.seats ? id : null);
        showGame(s, entriesFromHistory(s));
      } catch {
        await newGame();
      }
    },
    [newGame, showGame],
  );

  useEffect(() => {
    if (!gameId || !state || isOver(state)) {
      setLegal([]);
      return;
    }
    let cancelled = false;
    api
      .legalMoves(gameId)
      .then((moves) => !cancelled && setLegal(moves.map(parseMove)))
      .catch((e) => !cancelled && setError(message(e)));
    return () => {
      cancelled = true;
    };
  }, [gameId, state]);

  const applyResponse = useCallback((response: MoveResponse, search?: LogEntry["search"]) => {
    if (response.state.history.length <= plies.current) return; // already shown
    plies.current = response.state.history.length;
    setLog((previous) => [
      ...previous,
      {
        ply: response.state.history.length - 1,
        color: response.state.turn === "white" ? "black" : "white",
        notation: response.move,
        executed: response.executed,
        captured: response.captured,
        measurements: response.measurements,
        outcomes: response.measurements.map((m) => m.outcome),
        search,
      },
    ]);
    setState(response.state);
    setPicked([]);
    const collapsed = new Set(response.measurements.flatMap((m) => Object.keys(m.collapsed)));
    if (collapsed.size > 0) {
      setFlashing(collapsed);
      window.setTimeout(() => setFlashing(new Set()), 1200);
    }
  }, []);

  /** Apply a message from the live feed: the opponent's move, a player joining, or a catch-up. */
  const applyLive = useCallback(
    (live: LiveMessage) => {
      const fresh = live.state;
      if (fresh.game_id !== gameId) return;
      const known = plies.current;
      if (live.type === "move" && fresh.history.length === known + 1) {
        applyResponse(live);
      } else if (fresh.history.length > known) {
        // Missed moves while disconnected: rebuild the log from the history.
        plies.current = fresh.history.length;
        setState(fresh);
        setLog(entriesFromHistory(fresh));
      } else if (fresh.history.length === known) {
        setState(fresh); // a player joined
      }
    },
    [gameId, applyResponse],
  );

  /** Show how the squares entangled with `square` depend on it, or clear that with null. */
  const hover = (square: string | null) => {
    const token = ++hoverToken.current;
    if (!square || !gameId) {
      setCorrelations(null);
      return;
    }
    api
      .correlations(gameId, square)
      .then((c) => token === hoverToken.current && setCorrelations(c))
      .catch(() => setCorrelations(null));
  };

  return {
    state,
    gameId,
    online,
    legal,
    log,
    picked,
    setPicked,
    flipped,
    setFlipped,
    busy,
    error,
    notice,
    setNotice,
    setError,
    flashing,
    correlations,
    seat,
    run,
    showGame,
    newGame,
    resume,
    applyResponse,
    applyLive,
    hover,
  };
}
