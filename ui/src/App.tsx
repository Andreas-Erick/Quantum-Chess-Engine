import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { Board, GROUP_COLORS } from "./components/Board";
import { type LogEntry, MoveLog } from "./components/MoveLog";
import { completedMove, type Mode, nextSquares, parseMove, type ParsedMove } from "./moves";
import type { Color, Correlations, GameState, MoveResponse } from "./types";

const STORAGE_KEY = "quantum-chess:game-id";

const MODES: { id: Mode; label: string; hint: string }[] = [
  { id: "jump", label: "Move", hint: "piece → square" },
  { id: "split", label: "Split", hint: "piece → two squares" },
  { id: "merge", label: "Merge", hint: "two halves → square" },
];

function readStored(): string | null {
  // A ?game=<id> link opens that game; otherwise resume the last one played here.
  const linked = new URLSearchParams(window.location.search).get("game");
  if (linked) return linked;
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function store(gameId: string) {
  try {
    localStorage.setItem(STORAGE_KEY, gameId);
  } catch {
    // storage unavailable: the game just won't resume after a reload
  }
}

const isOver = (state: GameState) => !!state.winner || !!state.draw_reason;

function entriesFromHistory(state: GameState): LogEntry[] {
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

export default function App() {
  const [state, setState] = useState<GameState | null>(null);
  const [legal, setLegal] = useState<ParsedMove[]>([]);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [mode, setMode] = useState<Mode>("jump");
  const [picked, setPicked] = useState<string[]>([]);
  const [promotion, setPromotion] = useState("q");
  const [aiColor, setAiColor] = useState<Color | null>("black");
  const [iterations, setIterations] = useState(300);
  const [flipped, setFlipped] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flashing, setFlashing] = useState<Set<string>>(new Set());
  const [correlations, setCorrelations] = useState<Correlations | null>(null);
  const hoverToken = useRef(0);
  const started = useRef(false);
  const aiInFlight = useRef(false);

  const gameId = state?.game_id;

  const newGame = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const fresh = await api.init();
      store(fresh.game_id);
      setState(fresh);
      setLog([]);
      setPicked([]);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }, []);

  // Resume the last game if the server still has it, otherwise start a new one.
  useEffect(() => {
    if (started.current) return; // React StrictMode runs mount effects twice in development
    started.current = true;
    const stored = readStored();
    if (!stored) {
      void newGame();
      return;
    }
    api
      .state(stored)
      .then((s) => {
        store(s.game_id);
        setState(s);
        setLog(entriesFromHistory(s));
      })
      .catch(() => void newGame());
  }, [newGame]);

  useEffect(() => {
    if (!gameId || !state || isOver(state)) {
      setLegal([]);
      return;
    }
    let cancelled = false;
    api
      .legalMoves(gameId)
      .then((moves) => !cancelled && setLegal(moves.map(parseMove)))
      .catch((e) => !cancelled && setError(String(e.message ?? e)));
    return () => {
      cancelled = true;
    };
  }, [gameId, state]);

  const applyResponse = useCallback((response: MoveResponse, search?: LogEntry["search"]) => {
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

  const play = useCallback(
    async (notation: string) => {
      if (!gameId) return;
      setBusy(true);
      setError(null);
      try {
        applyResponse(await api.move(gameId, notation));
      } catch (e) {
        setError(String(e instanceof Error ? e.message : e));
        setPicked([]);
      } finally {
        setBusy(false);
      }
    },
    [gameId, applyResponse],
  );

  const aiMove = useCallback(async () => {
    if (!gameId || aiInFlight.current) return;
    aiInFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const response = await api.aiMove(gameId, iterations);
      applyResponse(response, response.search);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      aiInFlight.current = false;
      setBusy(false);
    }
  }, [gameId, iterations, applyResponse]);

  // Let the AI answer automatically when it is its turn.
  useEffect(() => {
    if (state && !isOver(state) && !busy && aiColor === state.turn) {
      void aiMove();
    }
  }, [state, busy, aiColor, aiMove]);

  const humanTurn = !!state && !isOver(state) && state.turn !== aiColor && !busy;
  const selectable = useMemo(
    () => (humanTurn ? nextSquares(mode, picked, legal) : new Set<string>()),
    [humanTurn, mode, picked, legal],
  );

  const onClick = (square: string) => {
    if (!humanTurn) return;
    if (picked.includes(square)) {
      setPicked(picked.filter((s) => s !== square));
      return;
    }
    if (!selectable.has(square)) {
      // Clicking a fresh piece restarts the selection.
      setPicked(nextSquares(mode, [], legal).has(square) ? [square] : []);
      return;
    }
    const next = [...picked, square];
    const move = completedMove(mode, next, legal, promotion);
    if (move) void play(move);
    else setPicked(next);
  };

  const onHover = (square: string | null) => {
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

  const checkSquares = Object.entries(state?.check ?? {});
  const last = log.length ? parseMove(log[log.length - 1].notation) : null;
  const counts = useMemo(() => {
    const result: Record<Mode, number> = { jump: 0, split: 0, merge: 0 };
    legal.forEach((m) => result[m.type]++);
    return result;
  }, [legal]);

  if (!state) {
    return <main className="loading">{error ? `Cannot reach the engine: ${error}` : "Connecting to the engine…"}</main>;
  }

  return (
    <main className="app">
      <header>
        <h1>
          Quantum Chess <span className="muted">· superposition, entanglement, measurement</span>
        </h1>
      </header>

      <section className="play">
        <Board
          state={state}
          flipped={flipped}
          selectable={selectable}
          picked={picked}
          lastMove={last ? [...last.sources, ...last.targets] : []}
          flashing={flashing}
          correlations={correlations}
          onClick={onClick}
          onHover={onHover}
        />
        <div className="status" role="status">
          {state.winner ? (
            <strong className="winner">{state.winner === "white" ? "White" : "Black"} captured the king and wins.</strong>
          ) : state.draw_reason ? (
            <strong className="winner">Draw by {state.draw_reason}.</strong>
          ) : busy && aiColor === state.turn ? (
            <span>AI is thinking…</span>
          ) : (
            <span>
              <span className={`dot ${state.turn}`} /> {state.turn === "white" ? "White" : "Black"} to move
              {checkSquares.length > 0 && (
                <strong className="check-warning">
                  {" "}
                  · Check! King attackable on{" "}
                  {checkSquares.map(([sq, p]) => (p < 1 ? `${sq} (${Math.round(p * 100)}%)` : sq)).join(", ")}
                </strong>
              )}
              {picked.length > 0 && <span className="muted"> · picked {picked.join(", ")}</span>}
            </span>
          )}
          {error && <span className="error">{error}</span>}
        </div>
      </section>

      <aside className="panel">
        <div className="card">
          <h2>Your move</h2>
          <div className="modes" role="radiogroup" aria-label="Move type">
            {MODES.map((m) => (
              <button
                key={m.id}
                role="radio"
                aria-checked={mode === m.id}
                className={mode === m.id ? "active" : ""}
                onClick={() => {
                  setMode(m.id);
                  setPicked([]);
                }}
                disabled={counts[m.id] === 0}
              >
                <strong>{m.label}</strong>
                <small>{m.hint}</small>
              </button>
            ))}
          </div>
          <label className="row">
            Promote to
            <select value={promotion} onChange={(e) => setPromotion(e.target.value)}>
              <option value="q">Queen</option>
              <option value="r">Rook</option>
              <option value="b">Bishop</option>
              <option value="n">Knight</option>
            </select>
          </label>
        </div>

        <div className="card">
          <h2>Game</h2>
          <label className="row">
            AI plays
            <select
              value={aiColor ?? "none"}
              onChange={(e) => setAiColor(e.target.value === "none" ? null : (e.target.value as Color))}
            >
              <option value="black">Black</option>
              <option value="white">White</option>
              <option value="none">Nobody</option>
            </select>
          </label>
          <label className="row">
            AI strength
            <input
              type="range"
              min={50}
              max={1500}
              step={50}
              value={iterations}
              onChange={(e) => setIterations(Number(e.target.value))}
            />
            <span className="muted num">{iterations}</span>
          </label>
          <div className="buttons">
            <button onClick={() => void aiMove()} disabled={busy || isOver(state)}>
              AI move now
            </button>
            <button onClick={() => setFlipped(!flipped)}>Flip board</button>
            <button onClick={() => void newGame()} disabled={busy}>
              New game
            </button>
          </div>
        </div>

        <div className="card log-card">
          <h2>Moves &amp; measurements</h2>
          <MoveLog entries={log} />
        </div>

        <details className="card legend">
          <summary>How to read the board</summary>
          <ul>
            <li>A faded piece with a percentage may or may not be there; the bar shows its probability.</li>
            <li>
              Squares with the same coloured ring are <em>entangled</em>
              {state.entanglement_groups.length > 0 && (
                <span className="swatches">
                  {state.entanglement_groups.map((_, i) => (
                    <span key={i} className="swatch" style={{ background: GROUP_COLORS[i % GROUP_COLORS.length] }} />
                  ))}
                </span>
              )}
              . Hover one to see how the others depend on it: ● if it is there, ○ if it is not.
            </li>
            <li>A split piece can split again (50% → 25% + 25%), but no part can drop below 25%.</li>
            <li>Capturing or entering an uncertain square measures it. Flashing squares just collapsed.</li>
            <li>
              Capture the enemy king to win. A red king square is in <em>check</em>: the opponent could try to
              capture it next move.
            </li>
            <li>Draw after 50 moves each without a pawn move, capture or measurement, or when only kings remain.</li>
          </ul>
        </details>
      </aside>
    </main>
  );
}
