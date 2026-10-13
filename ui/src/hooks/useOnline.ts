import { useCallback, useEffect, useRef } from "react";
import { ApiError, api } from "../api";
import { randomSeed, useDesktop } from "../desktop";
import { useLiveFeed } from "../live";
import { storage } from "../storage";
import type { Color } from "../types";
import { entriesFromHistory, type Game, message, setUrlGame } from "./useGame";

/**
 * Online games and the desktop app's hosting: creating and joining games, the live feed, and
 * opening the game a link points at when the page loads.
 */
export function useOnline(game: Game) {
  const [desktop, setHosting] = useDesktop();
  const started = useRef(false);
  const { gameId, online, run, showGame, newGame, resume, setNotice, setError } = game;

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
    [newGame, resume, showGame, setNotice, setError],
  );

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

  // The opponent's moves and arrivals come over the live feed.
  const connected = useLiveFeed(online && gameId ? gameId : null, game.applyLive);

  const create = (color: Color | "random") =>
    run(async () => {
      // In the desktop app, start listening on the local network first: the invite link
      // must point at an address the friend can reach.
      if (desktop?.ownPage) setHosting({ lanUrl: await desktop.api.host() });
      const created = await api.createOnline(color);
      storage.setSeat(created.game_id, { color: created.color, token: created.token });
      storage.setGameId(created.game_id);
      setUrlGame(created.game_id);
      setNotice(null);
      showGame(created.state, []);
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
