// Who moves next, and what the page says while it waits: decided in one place from the game
// on screen, this browser's seat, the tutorial and the AI.

import type { Color, GameState, Seat } from "./types";

/** Who plays the side to move: this player, the AI, the friend in an online game, or nobody
 * (the game is over, the friend hasn't joined yet, or the lesson is done). */
export type Mover = "me" | "ai" | "friend" | "nobody";

export interface Table {
  /** This browser's seat in an online game; null when watching or playing locally. */
  seat: Seat | null;
  /** In the tutorial: whether the lesson is done. Null outside the tutorial. */
  lesson: { done: boolean } | null;
  /** The colour the AI plays in a local game, or null. */
  ai: Color | null;
}

const colorName = (color: Color) => (color === "white" ? "White" : "Black");

export const isOver = (state: GameState) => !!state.winner || !!state.draw_reason;
export const bothSeated = (state: GameState) => !!state.seats?.white && !!state.seats.black;

export function mover(state: GameState, table: Table): Mover {
  if (isOver(state)) return "nobody";
  if (state.seats) {
    if (!bothSeated(state)) return "nobody";
    return table.seat?.color === state.turn ? "me" : "friend";
  }
  if (table.lesson) return table.lesson.done ? "nobody" : "me";
  return table.ai === state.turn ? "ai" : "me";
}

/** What the status line says while it isn't this player's move, or null. */
export function waitingFor(state: GameState, table: Table, busy: boolean): string | null {
  const who = mover(state, table);
  if (who === "ai") return busy ? "AI is thinking…" : null;
  if (state.seats && !isOver(state) && !bothSeated(state)) return "Waiting for your friend to join…";
  if (who === "friend" && table.seat) return `Waiting for ${colorName(state.turn)} to move…`;
  return null;
}
