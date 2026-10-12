import { useState } from "react";
import type { Desktop } from "../desktop";
import type { Color, GameState, Seat } from "../types";

interface OnlineCardProps {
  state: GameState;
  seat: Seat | null;
  connected: boolean;
  busy: boolean;
  /** The desktop app's bridge, or null in a browser. */
  desktop: Desktop | null;
  onCreate: (color: Color | "random") => void;
  /** Desktop only: join from an invite link. */
  onJoin: (link: string) => void;
  /** Desktop only: also accept players from the internet. */
  onShareOnline: () => Promise<void>;
  /** Desktop only: stop accepting players from the network and the internet. */
  onStopHosting: () => void;
}

const LOCAL_HOSTS = ["localhost", "127.0.0.1", "[::1]"];

export function inviteLink(gameId: string, base?: string | null): string {
  const root = base ? base.replace(/\/$/, "") + "/" : `${window.location.origin}${window.location.pathname}`;
  return `${root}?join=${encodeURIComponent(gameId)}`;
}

const short = (hex: string) => `${hex.slice(0, 10)}…`;

export function OnlineCard({
  state,
  seat,
  connected,
  busy,
  desktop,
  onCreate,
  onJoin,
  onShareOnline,
  onStopHosting,
}: OnlineCardProps) {
  const [color, setColor] = useState<Color | "random">("white");
  const [sharing, setSharing] = useState(false);
  const [copied, setCopied] = useState(false);
  const [joinLink, setJoinLink] = useState("");
  const hosting = !!desktop?.ownPage;
  const back = desktop && !desktop.ownPage && (
    <button onClick={() => void desktop.api.home()}>Back to my games</button>
  );
  const hostingNote = hosting && desktop.lanUrl && (
    <div className="hosting">
      <p className="muted small">
        {desktop.publicUrl ? (
          <>
            Hosting at <code>{desktop.lanUrl}</code> and on the internet at <code>{desktop.publicUrl}</code>. Anyone
            with a link can join or watch your online games until you stop.
          </>
        ) : (
          <>
            Hosting at <code>{desktop.lanUrl}</code>. Anyone on this network can reach it until you stop.
          </>
        )}
      </p>
      <div className="buttons">
        <button onClick={onStopHosting} disabled={busy}>
          Stop hosting
        </button>
      </div>
    </div>
  );

  if (!state.seats) {
    return (
      <section className="card" aria-label="Play online">
        <h2>Play a friend</h2>
        {back ? (
          <>
            <p className="muted small">You are on a friend's game server.</p>
            <div className="buttons">{back}</div>
          </>
        ) : (
          <>
            <p className="muted small">
              {hosting
                ? "Host a game on your network and send your friend the link. They can join from their own Quantum Chess Engine app or a browser. Only host on networks you trust, like your home Wi-Fi."
                : "Start a game and send your friend the link. Each of you plays from your own device."}
            </p>
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
                {hosting ? "Host a game" : "Create invite link"}
              </button>
            </div>
            {hosting && (
              <form
                className="invite join"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (joinLink.trim()) onJoin(joinLink.trim());
                }}
              >
                <input
                  value={joinLink}
                  onChange={(e) => setJoinLink(e.target.value)}
                  placeholder="Paste a friend's invite link"
                  aria-label="Invite link to join"
                />
                <button type="submit" disabled={busy || !joinLink.trim()}>
                  Join
                </button>
              </form>
            )}
            {hostingNote}
          </>
        )}
      </section>
    );
  }

  const link = inviteLink(state.game_id, desktop?.publicUrl ?? desktop?.lanUrl);
  const opponentHere = state.seats.white && state.seats.black;
  const over = !!state.winner || !!state.draw_reason;
  const fairness = state.fairness;
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
          {hosting && desktop.publicUrl ? (
            <p className="muted small">This link works from anywhere while the app is open.</p>
          ) : hosting ? (
            <>
              <p className="muted small">
                This link works for a friend on the same network. If they can't connect, allow Quantum Chess Engine through
                your firewall, on private networks only.
              </p>
              <div className="buttons">
                <button
                  onClick={() => {
                    setSharing(true);
                    void onShareOnline().finally(() => setSharing(false));
                  }}
                  disabled={busy}
                >
                  {sharing ? "Opening internet link…" : "Get an internet link"}
                </button>
              </div>
              <p className="muted small">
                {sharing
                  ? "This takes a few seconds. The first time, the app installs cloudflared, which can take a minute."
                  : "For a friend somewhere else: a free, temporary Cloudflare link to your game."}
              </p>
            </>
          ) : (
            LOCAL_HOSTS.includes(window.location.hostname) && (
              <p className="muted small">
                This server runs on your computer, so the link only works here. To play a friend elsewhere, use the
                desktop app's Host button or run the server where they can reach it (see the README).
              </p>
            )
          )}
        </>
      )}
      {fairness && opponentHere && (
        <p className="muted small fairness">
          {over && fairness.secret ? (
            <>
              Dice revealed. Check them:{" "}
              {desktop ? (
                <>
                  <strong>Game ▸ Verify this game's dice</strong> in the menu
                </>
              ) : (
                <code>
                  python -m api.fairness {window.location.origin}/?game={state.game_id}
                  {seat?.seed ? ` --seed ${seat.seed}` : ""}
                </code>
              )}
            </>
          ) : (
            <>
              Fair dice: both players seeded them, and the server's share ({short(fairness.commitment)}) was fixed before
              anyone joined. It is revealed when the game ends.
            </>
          )}
        </p>
      )}
      {hostingNote}
      {back && <div className="buttons">{back}</div>}
    </section>
  );
}
