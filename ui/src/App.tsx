import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { Board, GROUP_COLORS } from "./components/Board";
import { type LogEntry, MoveLog } from "./components/MoveLog";
import { OnlineCard } from "./components/OnlineCard";
import { TutorialCard } from "./components/TutorialCard";
import { randomSeed, useDesktop } from "./desktop";
import { useLiveFeed } from "./live";
import { completedMove, type Mode, nextSquares, parseMove, type ParsedMove } from "./moves";
import { storage } from "./storage";
import { accepts, LESSONS, type TutorialProgress } from "./tutorial/lessons";
import type { Color, Correlations, GameState, LevelInfo, LevelName, LiveMessage, MoveResponse, Seat } from "./types";

const MODES: { id: Mode; label: string; hint: string }[] = [
  { id: "jump", label: "Move", hint: "piece → square" },
  { id: "split", label: "Split", hint: "piece → two squares" },
  { id: "merge", label: "Merge", hint: "two halves → square" },
];

const REPLY_DELAY_MS = 600; // let the player see their move before a tutorial reply

const isOver = (state: GameState) => !!state.winner || !!state.draw_reason;
// Errors from fetch are Errors; errors from the desktop bridge are plain { message } objects.
const message = (e: unknown) =>
  String(e && typeof e === "object" && "message" in e ? (e as { message: unknown }).message : e);
const colorName = (color: Color) => (color === "white" ? "White" : "Black");

/** Keep the address bar pointing at an online game, so a reload reopens it. */
function setUrlGame(gameId: string | null) {
  window.history.replaceState(null, "", gameId ? `?game=${encodeURIComponent(gameId)}` : window.location.pathname);
}

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
  const [levels, setLevels] = useState<LevelInfo[]>([]);
  const [level, setLevel] = useState<LevelName>(() => storage.level() ?? "medium");
  const [flipped, setFlipped] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [flashing, setFlashing] = useState<Set<string>>(new Set());
  const [correlations, setCorrelations] = useState<Correlations | null>(null);
  const [seat, setSeat] = useState<Seat | null>(null);
  const [tutorial, setTutorial] = useState<TutorialProgress | null>(null);
  const [lessonsDone, setLessonsDone] = useState<string[]>(() => storage.lessonsDone());
  const [desktop, setLanUrl] = useDesktop();
  const hoverToken = useRef(0);
  const started = useRef(false);
  const aiInFlight = useRef(false);
  // Plies already shown. Updated synchronously, so a move that arrives twice (as the HTTP
  // response and on the live feed) is applied once.
  const plies = useRef(0);

  const gameId = state?.game_id;
  const online = !!state?.seats;
  const step = tutorial ? LESSONS[tutorial.lesson].steps[tutorial.step] : null;
  // The AI only plays in ordinary local games.
  const ai = online || tutorial ? null : aiColor;

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
        setTutorial(null);
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

  const join = useCallback(
    async (id: string) => {
      if (storage.seat(id)) return resume(id); // already playing in this game
      try {
        const seed = randomSeed(); // our share of the dice, kept to verify them afterwards
        const joined = await api.joinOnline(id, seed);
        storage.setSeat(id, { color: joined.color, token: joined.token, seed });
        storage.setGameId(id);
        setUrlGame(id);
        showGame(joined.state, entriesFromHistory(joined.state));
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          await resume(id);
          setNotice("Both seats are taken, so you are watching this game.");
        } else {
          await newGame();
          setError(`Could not join that game: ${message(e)}`);
        }
      }
    },
    [newGame, resume, showGame],
  );

  const createOnline = (color: Color | "random") =>
    run(async () => {
      // In the desktop app, start listening on the local network first: the invite link
      // must point at an address the friend can reach.
      if (desktop?.ownPage) setLanUrl(await desktop.api.host());
      const created = await api.createOnline(color);
      storage.setSeat(created.game_id, { color: created.color, token: created.token });
      storage.setGameId(created.game_id);
      setUrlGame(created.game_id);
      setNotice(null);
      showGame(created.state, []);
    });

  useEffect(() => {
    api
      .levels()
      .then((list) => {
        setLevels(list);
        if (!storage.level()) setLevel(list.find((l) => l.default)?.name ?? "medium");
      })
      .catch(() => setLevels([]));
  }, []);

  // Open the game from the link (?join=<id> joins it, ?game=<id> opens it) or resume the last one.
  useEffect(() => {
    if (started.current) return; // React StrictMode runs mount effects twice in development
    started.current = true;
    const params = new URLSearchParams(window.location.search);
    // The desktop app joins games itself and hands the seat over in the fragment.
    const handed = /^#seat=(white|black)\.(.+)$/.exec(window.location.hash);
    const gameParam = params.get("game");
    if (handed && gameParam) storage.setSeat(gameParam, { color: handed[1] as Color, token: handed[2] });
    const joinId = params.get("join");
    if (joinId) {
      void join(joinId);
      return;
    }
    const stored = gameParam ?? storage.gameId();
    if (stored) void resume(stored);
    else void newGame();
  }, [join, newGame, resume]);

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

  // --- Online: the opponent's moves and arrivals come over the live feed ---------------

  const onLive = useCallback(
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
  const connected = useLiveFeed(online && gameId ? gameId : null, onLive);

  // --- Tutorial ----------------------------------------------------------------------

  const startLesson = (index: number) =>
    run(async () => {
      const lesson = LESSONS[index];
      const fresh = await api.init(lesson.fen);
      setUrlGame(null);
      setNotice(null);
      setFlipped(false);
      showGame(fresh, []);
      for (const notation of lesson.setup ?? []) applyResponse(await api.move(fresh.game_id, notation));
      setTutorial({ lesson: index, step: 0, done: false });
      setMode(lesson.steps[0].mode);
    });

  const exitTutorial = () => {
    setTutorial(null);
    const stored = storage.gameId();
    void run(() => (stored ? resume(stored) : newGame()));
  };

  const advanceTutorial = async (id: string, progress: TutorialProgress) => {
    const lesson = LESSONS[progress.lesson];
    const current = lesson.steps[progress.step];
    if (progress.step + 1 < lesson.steps.length) {
      if (current.reply) {
        await new Promise((resolve) => window.setTimeout(resolve, REPLY_DELAY_MS));
        applyResponse(await api.move(id, current.reply));
      }
      setTutorial({ ...progress, step: progress.step + 1 });
      setMode(lesson.steps[progress.step + 1].mode);
      return;
    }
    setTutorial({ ...progress, done: true });
    if (!lessonsDone.includes(lesson.id)) {
      const done = [...lessonsDone, lesson.id];
      setLessonsDone(done);
      storage.setLessonsDone(done);
    }
  };

  // --- Moves ---------------------------------------------------------------------------

  const play = async (notation: string) => {
    if (!gameId) return;
    setBusy(true);
    setError(null);
    try {
      applyResponse(await api.move(gameId, notation, seat?.token));
      if (tutorial) await advanceTutorial(gameId, tutorial);
    } catch (e) {
      setError(message(e));
      setPicked([]);
    } finally {
      setBusy(false);
    }
  };

  const aiMove = useCallback(async () => {
    if (!gameId || aiInFlight.current) return;
    aiInFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const response = await api.aiMove(gameId, level);
      applyResponse(response, response.search);
    } catch (e) {
      setError(message(e));
    } finally {
      aiInFlight.current = false;
      setBusy(false);
    }
  }, [gameId, level, applyResponse]);

  // Let the AI answer automatically when it is its turn.
  useEffect(() => {
    if (state && !isOver(state) && !busy && ai === state.turn) {
      void aiMove();
    }
  }, [state, busy, ai, aiMove]);

  const bothSeated = !!state?.seats && state.seats.white && state.seats.black;
  const myTurn = !state
    ? false
    : online
      ? seat?.color === state.turn && bothSeated
      : tutorial
        ? !tutorial.done
        : state.turn !== ai;
  const humanTurn = !!state && !isOver(state) && !busy && myTurn;

  // In the tutorial, only the moves the lesson asks for can be played.
  const playable = useMemo(
    () => (step ? legal.filter((m) => accepts(step, m.notation)) : legal),
    [legal, step],
  );
  const selectable = useMemo(
    () => (humanTurn ? nextSquares(mode, picked, playable) : new Set<string>()),
    [humanTurn, mode, picked, playable],
  );

  const onClick = (square: string) => {
    if (!humanTurn) return;
    if (picked.includes(square)) {
      setPicked(picked.filter((s) => s !== square));
      return;
    }
    if (!selectable.has(square)) {
      // Clicking a fresh piece restarts the selection.
      setPicked(nextSquares(mode, [], playable).has(square) ? [square] : []);
      return;
    }
    const next = [...picked, square];
    const move = completedMove(mode, next, playable, promotion);
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
    playable.forEach((m) => result[m.type]++);
    return result;
  }, [playable]);

  if (!state) {
    return <main className="loading">{error ? `Cannot reach the engine: ${error}` : "Connecting to the engine…"}</main>;
  }

  const lastOwnMove = tutorial?.done ? log[log.length - 1] : undefined;

  let waiting: string | null = null;
  if (busy && ai === state.turn) waiting = "AI is thinking…";
  else if (online && !bothSeated) waiting = "Waiting for your friend to join…";
  else if (online && seat && seat.color !== state.turn) waiting = `Waiting for ${colorName(state.turn)} to move…`;

  return (
    <main className="app">
      <header>
        <h1>
          Quantum Chess <span className="muted">· superposition, entanglement, measurement</span>
        </h1>
        {!tutorial && (
          <div className="header-actions">
            {lessonsDone.length === 0 && <span className="muted small">New here?</span>}
            <button className="primary" onClick={() => void startLesson(0)} disabled={busy}>
              Learn to play
            </button>
          </div>
        )}
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
            <strong className="winner">{colorName(state.winner)} captured the king and wins.</strong>
          ) : state.draw_reason ? (
            <strong className="winner">Draw by {state.draw_reason}.</strong>
          ) : waiting ? (
            <span>{waiting}</span>
          ) : (
            <span>
              <span className={`dot ${state.turn}`} /> {colorName(state.turn)} to move
              {online && seat?.color === state.turn && " (you)"}
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
          {notice && <span className="muted">{notice}</span>}
          {error && <span className="error">{error}</span>}
        </div>
      </section>

      <aside className="panel">
        {tutorial && (
          <TutorialCard
            progress={tutorial}
            lessonsDone={lessonsDone}
            measurements={lastOwnMove?.measurements ?? []}
            busy={busy}
            onLesson={(i) => void startLesson(i)}
            onExit={exitTutorial}
          />
        )}

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

        {!tutorial && (
          <div className="card">
            <h2>Game</h2>
            {!online && (
              <>
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
                {levels.length > 0 && (
                  <>
                    <div className="modes levels" role="radiogroup" aria-label="AI strength">
                      {levels.map((l) => (
                        <button
                          key={l.name}
                          role="radio"
                          aria-checked={level === l.name}
                          className={level === l.name ? "active" : ""}
                          onClick={() => {
                            setLevel(l.name);
                            storage.setLevel(l.name);
                          }}
                        >
                          <strong>{l.label}</strong>
                        </button>
                      ))}
                    </div>
                    <p className="muted level-hint">{levels.find((l) => l.name === level)?.description}</p>
                  </>
                )}
              </>
            )}
            <div className="buttons">
              {!online && (
                <button onClick={() => void aiMove()} disabled={busy || isOver(state)}>
                  AI move now
                </button>
              )}
              <button onClick={() => setFlipped(!flipped)}>Flip board</button>
              <button onClick={() => void newGame()} disabled={busy}>
                {online ? "Leave & new game" : "New game"}
              </button>
            </div>
          </div>
        )}

        {!tutorial && (
          <OnlineCard
            state={state}
            seat={seat}
            connected={connected}
            busy={busy}
            desktop={desktop}
            onCreate={createOnline}
            onJoin={(link) => void run(async () => desktop?.api.join(link))}
          />
        )}

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
