import { useState } from "react";
import type { Color, GameState, Seat } from "../types";

interface OnlineCardProps {
  state: GameState;
  seat: Seat | null;
  connected: boolean;
  busy: boolean;
  onCreate: (color: Color | "random") => void;
}

const LOCAL_HOSTS = ["localhost", "127.0.0.1", "[::1]"];

export function inviteLink(gameId: string): string {
  return `${window.location.origin}${window.location.pathname}?join=${encodeURIComponent(gameId)}`;
}

export function OnlineCard({ state, seat, connected, busy, onCreate }: OnlineCardProps) {
  const [color, setColor] = useState<Color | "random">("white");
  const [copied, setCopied] = useState(false);

  if (!state.seats) {
    return (
      <section className="card" aria-label="Play online">
        <h2>Play a friend online</h2>
        <p className="muted small">Start a game and send your friend the link. Each of you plays from your own device.</p>
        <label className="row">
          I play
          <select value={color} onChange={(e) => setColor(e.target.value as Color | "random")}>
            <option value="white">White</option>
            <option value="black">Black</option>
            <option value="random">Random</option>
          </select>
        </label>
        <div className="buttons">
          <button className="primary" onClick={() => onCreate(color)} disabled={busy}>
            Create invite link
          </button>
        </div>
      </section>
    );
  }

  const link = inviteLink(state.game_id);
  const opponentHere = state.seats.white && state.seats.black;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard blocked: the link is selectable in the field
    }
  };

  return (
    <section className="card" aria-label="Online game">
      <h2>
        Online game{" "}
        <span className={`live ${connected ? "on" : ""}`}>{connected ? "● live" : "○ reconnecting…"}</span>
      </h2>
      <p>
        {seat ? (
          <>
            You play <span className={`dot ${seat.color}`} /> <strong>{seat.color === "white" ? "White" : "Black"}</strong>
            .
          </>
        ) : (
          "You are watching this game."
        )}{" "}
        {opponentHere ? "Both players are here." : seat ? "Waiting for your friend to join…" : ""}
      </p>
      {seat && !opponentHere && (
        <>
          <div className="invite">
            <input readOnly value={link} aria-label="Invite link" onFocus={(e) => e.target.select()} />
            <button onClick={() => void copy()}>{copied ? "Copied" : "Copy"}</button>
          </div>
          {LOCAL_HOSTS.includes(window.location.hostname) && (
            <p className="muted small">
              This server runs on your computer, so the link only works here. To play a friend elsewhere, run the
              server where they can reach it (see the README).
            </p>
          )}
        </>
      )}
    </section>
  );
}
