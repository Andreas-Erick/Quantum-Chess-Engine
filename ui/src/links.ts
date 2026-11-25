// The formats of game links. The desktop app and the server's tools read and build the same
// formats in api/links.py; change both together.
//
// - `?game=<id>` opens a game, `?join=<id>` invites a friend to join it.
// - `#seat=<color>.<token>` hands a seat to the page in the fragment, which browsers never send
//   to a server. The desktop app uses it after joining a game itself.

import type { Seat } from "./types";

/** What the page's address asks for when it loads. */
export interface LinkRequest {
  /** The game to open (`?game=`), if any. */
  game: string | null;
  /** The game to join (`?join=`), if any. */
  join: string | null;
  /** A seat handed over in the fragment, for `game`. */
  seat: Seat | null;
}

export function readLink(location: { search: string; hash: string }): LinkRequest {
  const params = new URLSearchParams(location.search);
  const game = params.get("game");
  const handed = /^#seat=(white|black)\.(.+)$/.exec(location.hash);
  return {
    game,
    join: params.get("join"),
    seat: handed && game ? { color: handed[1] as Seat["color"], token: handed[2] } : null,
  };
}

/** The page's address for `gameId` (`?game=<id>`), or the bare page for null. */
export function gameAddress(gameId: string | null, pathname: string): string {
  return gameId ? `?game=${encodeURIComponent(gameId)}` : pathname;
}

/** The link a friend opens to join `gameId`: on `base` if given, else on this page. */
export function inviteLink(
  gameId: string,
  base: string | null | undefined,
  here: { origin: string; pathname: string },
) {
  const root = base ? `${base.replace(/\/$/, "")}/` : `${here.origin}${here.pathname}`;
  return `${root}?join=${encodeURIComponent(gameId)}`;
}
