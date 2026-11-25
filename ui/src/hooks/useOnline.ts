import { useCallback, useEffect, useRef } from "react";
import { ApiError, api } from "../api";
import { randomSeed, useDesktop } from "../desktop";
import { readLink } from "../links";
import { useLiveFeed } from "../live";
import { storage } from "../storage";
import type { Color } from "../types";
import { type Game, message } from "./useGame";

/**
 * Online games and the desktop app's hosting: creating and joining games, the live feed, and
 * opening the game a link points at when the page loads.
 */
export function useOnline(game: Game) {
  const [desktop, setHosting] = useDesktop();
  const started = useRef(false);
  const { gameId, online, run, open, newGame, resume, setNotice, setError } = game;

  const join = useCallback(
    async (id: string) => {
      if (storage.seat(id)) return resume(id); // already playing in this game
      try {
        const seed = randomSeed(); // our share of the dice, kept to verify them afterwards
        const joined = await api.joinOnline(id, seed);
        open(joined.state, { seat: { color: joined.color, token: joined.token, seed } });
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
    [newGame, resume, open, setNotice, setError],
  );

  // Open the game from the link (?join=<id> joins it, ?game=<id> opens it) or resume the last one.
  useEffect(() => {
    if (started.current) return; // React StrictMode runs mount effects twice in development
    started.current = true;
    // The desktop app joins games itself and hands the seat over in the fragment.
    const link = readLink(window.location);
    if (link.join) {
      void join(link.join);
      return;
    }
    const stored = link.game ?? storage.gameId();
    if (stored) void resume(stored, link.seat);
    else void newGame();
  }, [join, newGame, resume]);

  // The opponent's moves and arrivals come over the live feed.
  const connected = useLiveFeed(online && gameId ? gameId : null, game.applyLive);

  const create = (color: Color | "random") =>
    run(async () => {
      // In the desktop app, start listening on the local network first: the invite link
      // must point at an address the friend can reach.
      if (desktop?.ownPage) setHosting({ lanUrl: await desktop.api.host() });
      const created = await api.createOnline(color);
      open(created.state, { seat: { color: created.color, token: created.token } });
    });

  /** Desktop app: join from an invite link (the app opens the game itself). */
  const joinLink = (link: string) => void run(async () => desktop?.api.join(link));

  /** Desktop app: also accept players from the internet. */
  const shareOnline = () =>
    run(async () => {
      const publicUrl = await desktop?.api.share_online();
      if (publicUrl) setHosting({ publicUrl });
    });

  const stopHosting = () =>
    void run(async () => {
      await desktop?.api.stop_hosting();
      setHosting({ lanUrl: null, publicUrl: null });
    });

  return { desktop, connected, create, joinLink, shareOnline, stopHosting };
}
