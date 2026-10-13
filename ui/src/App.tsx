import { useMemo, useState } from "react";
import { api } from "./api";
import { Board, GROUP_COLORS } from "./components/Board";
import { MoveLog } from "./components/MoveLog";
import { OnlineCard } from "./components/OnlineCard";
import { TutorialCard } from "./components/TutorialCard";
import { useAi } from "./hooks/useAi";
import { isOver, useGame } from "./hooks/useGame";
import { useOnline } from "./hooks/useOnline";
import { useTutorial } from "./hooks/useTutorial";
import { completedMove, type Mode, nextSquares, parseMove } from "./moves";
import { accepts } from "./tutorial/lessons";
import type { Color } from "./types";

const MODES: { id: Mode; label: string; hint: string }[] = [
  { id: "jump", label: "Move", hint: "piece → square" },
  { id: "split", label: "Split", hint: "piece → two squares" },
  { id: "merge", label: "Merge", hint: "two halves → square" },
];

const colorName = (color: Color) => (color === "white" ? "White" : "Black");

export default function App() {
  const [mode, setMode] = useState<Mode>("jump");
  const [promotion, setPromotion] = useState("q");
  const game = useGame();
  const tutorial = useTutorial(game, setMode);
  // The AI only plays in ordinary local games.
  const ai = useAi(game, !game.online && !tutorial.progress);
  const online = useOnline(game);
  const { state, gameId, legal, log, picked, setPicked, busy, error, seat } = game;
  const step = tutorial.step;

  const play = async (notation: string) => {
    if (!gameId) return;
    await game.run(async () => {
      try {
        game.applyResponse(await api.move(gameId, notation, seat?.token));
        await tutorial.advance(gameId);
      } catch (e) {
        setPicked([]);
        throw e;
      }
    });
  };

  const bothSeated = !!state?.seats && state.seats.white && state.seats.black;
  const myTurn = !state
    ? false
    : game.online
      ? seat?.color === state.turn && bothSeated
      : tutorial.progress
        ? !tutorial.progress.done
        : state.turn !== ai.playing;
  const humanTurn = !!state && !isOver(state) && !busy && myTurn;

  // In the tutorial, only the moves the lesson asks for can be played.
  const playable = useMemo(() => (step ? legal.filter((m) => accepts(step, m.notation)) : legal), [legal, step]);
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

  const checkSquares = Object.entries(state?.check ?? {});
  const last = log.length ? parseMove(log[log.length - 1].notation) : null;
  const counts = useMemo(() => {
    const result: Record<Mode, number> = { jump: 0, split: 0, merge: 0 };
    for (const m of playable) result[m.type]++;
    return result;
  }, [playable]);

  if (!state) {
    return <main className="loading">{error ? `Cannot reach the engine: ${error}` : "Connecting to the engine…"}</main>;
  }

  const lastOwnMove = tutorial.progress?.done ? log[log.length - 1] : undefined;

  let waiting: string | null = null;
  if (busy && ai.playing === state.turn) waiting = "AI is thinking…";
  else if (game.online && !bothSeated) waiting = "Waiting for your friend to join…";
  else if (game.online && seat && seat.color !== state.turn) waiting = `Waiting for ${colorName(state.turn)} to move…`;

  return (
    <main className="app">
      <header>
        <div className="brand">
          <img src="/favicon.svg" alt="" width="40" height="40" />
          <div>
            <h1>Quantum Chess Engine</h1>
            <p className="tagline">Superposition, entanglement, measurement</p>
          </div>
        </div>
        {!tutorial.progress && (
          <div className="header-actions">
            {tutorial.lessonsDone.length === 0 && <span className="muted small">New here?</span>}
            <button type="button" className="primary" onClick={() => void tutorial.start(0)} disabled={busy}>
              Learn to play
            </button>
          </div>
        )}
      </header>

      <section className="play">
        <Board
          state={state}
          flipped={game.flipped}
          selectable={selectable}
          picked={picked}
          lastMove={last ? [...last.sources, ...last.targets] : []}
          flashing={game.flashing}
          correlations={game.correlations}
          onClick={onClick}
          onHover={game.hover}
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
              {game.online && seat?.color === state.turn && " (you)"}
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
          {game.notice && <span className="muted">{game.notice}</span>}
          {error && <span className="error">{error}</span>}
        </div>
      </section>

      <aside className="panel">
        {tutorial.progress && (
          <TutorialCard
            progress={tutorial.progress}
            lessonsDone={tutorial.lessonsDone}
            measurements={lastOwnMove?.measurements ?? []}
            busy={busy}
            onLesson={(i) => void tutorial.start(i)}
            onExit={tutorial.exit}
          />
        )}

        <div className="card">
          <h2>Your move</h2>
          <div className="modes" role="radiogroup" aria-label="Move type">
            {MODES.map((m) => (
              <button
                type="button"
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

        {!tutorial.progress && (
          <div className="card">
            <h2>Game</h2>
            {!game.online && (
              <>
                <label className="row">
                  AI plays
                  <select
                    value={ai.color ?? "none"}
                    onChange={(e) => ai.setColor(e.target.value === "none" ? null : (e.target.value as Color))}
                  >
                    <option value="black">Black</option>
                    <option value="white">White</option>
                    <option value="none">Nobody</option>
                  </select>
                </label>
                {ai.levels.length > 0 && (
                  <>
                    <div className="modes levels" role="radiogroup" aria-label="AI strength">
                      {ai.levels.map((l) => (
                        <button
                          type="button"
                          key={l.name}
                          role="radio"
                          aria-checked={ai.level === l.name}
                          className={ai.level === l.name ? "active" : ""}
                          onClick={() => ai.chooseLevel(l.name)}
                        >
                          <strong>{l.label}</strong>
                        </button>
                      ))}
                    </div>
                    <p className="muted level-hint">{ai.levels.find((l) => l.name === ai.level)?.description}</p>
                  </>
                )}
              </>
            )}
            <div className="buttons">
              {!game.online && (
                <button type="button" onClick={() => void ai.move()} disabled={busy || isOver(state)}>
                  AI move now
                </button>
              )}
              <button type="button" onClick={() => game.setFlipped(!game.flipped)}>
                Flip board
              </button>
              <button type="button" onClick={() => void game.newGame()} disabled={busy}>
                {game.online ? "Leave & new game" : "New game"}
              </button>
            </div>
          </div>
        )}

        {!tutorial.progress && (
          <OnlineCard
            state={state}
            seat={seat}
            connected={online.connected}
            busy={busy}
            desktop={online.desktop}
            onCreate={online.create}
            onJoin={online.joinLink}
            onShareOnline={online.shareOnline}
            onStopHosting={online.stopHosting}
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
                    // biome-ignore lint/suspicious/noArrayIndexKey: one swatch per group, identified by its index
                    <span key={i} className="swatch" style={{ background: GROUP_COLORS[i % GROUP_COLORS.length] }} />
                  ))}
                </span>
              )}
              . Hover one to see how the others depend on it: ● if it is there, ○ if it is not.
            </li>
            <li>A split piece can split again (50% → 25% + 25%), but no part can drop below 25%.</li>
            <li>Capturing or entering an uncertain square measures it. Flashing squares just collapsed.</li>
            <li>
              Capture the enemy king to win. A red king square is in <em>check</em>: the opponent could try to capture
              it next move.
            </li>
            <li>Draw after 50 moves each without a pawn move, capture or measurement, or when only kings remain.</li>
          </ul>
        </details>
      </aside>
    </main>
  );
}
