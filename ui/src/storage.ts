// Per-browser conveniences in localStorage. Every access may throw (private windows, blocked
// storage), and the app must work without it: a game just won't resume after a reload.

import type { LevelName, Seat } from "./types";

const GAME_KEY = "quantum-chess:game-id";
const LEVEL_KEY = "quantum-chess:level";
const SEAT_PREFIX = "quantum-chess:seat:";
const TUTORIAL_KEY = "quantum-chess:tutorial-done";

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // storage unavailable
  }
}

export const storage = {
  gameId: () => read(GAME_KEY),
  setGameId: (gameId: string) => write(GAME_KEY, gameId),

  level: (): LevelName | null => {
    const stored = read(LEVEL_KEY);
    return stored === "easy" || stored === "medium" || stored === "hard" ? stored : null;
  },
  setLevel: (level: LevelName) => write(LEVEL_KEY, level),

  /** The seat this browser holds in an online game, if any. */
  seat: (gameId: string): Seat | null => {
    try {
      const seat = JSON.parse(read(SEAT_PREFIX + gameId) ?? "null");
      if (!seat || (seat.color !== "white" && seat.color !== "black") || typeof seat.token !== "string") return null;
      return typeof seat.seed === "string" ? { color: seat.color, token: seat.token, seed: seat.seed } : { color: seat.color, token: seat.token };
    } catch {
      return null;
    }
  },
  setSeat: (gameId: string, seat: Seat) => write(SEAT_PREFIX + gameId, JSON.stringify(seat)),

  /** Lessons finished, by id. */
  lessonsDone: (): string[] => {
    try {
      const done = JSON.parse(read(TUTORIAL_KEY) ?? "[]");
      return Array.isArray(done) ? done.filter((id) => typeof id === "string") : [];
    } catch {
      return [];
    }
  },
  setLessonsDone: (ids: string[]) => write(TUTORIAL_KEY, JSON.stringify(ids)),
};
