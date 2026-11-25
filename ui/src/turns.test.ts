import { describe, expect, it } from "vitest";
import split from "./fixtures/split.json";
import { mover, type Table, waitingFor } from "./turns";
import type { GameState } from "./types";

const local: GameState = { ...(split.state as GameState), turn: "white", seats: null, winner: null, draw_reason: null };
const online: GameState = { ...local, seats: { white: true, black: true } };
const table = (over: Partial<Table> = {}): Table => ({ seat: null, lesson: null, ai: "black", ...over });

describe("mover", () => {
  it("in a local game, the AI plays its colour and the player the other", () => {
    expect(mover(local, table())).toBe("me");
    expect(mover({ ...local, turn: "black" }, table())).toBe("ai");
    expect(mover({ ...local, turn: "black" }, table({ ai: null }))).toBe("me");
  });

  it("in an online game, the seat decides, and nobody moves before the friend joins", () => {
    const white = { color: "white", token: "t" } as const;
    expect(mover(online, table({ seat: white }))).toBe("me");
    expect(mover({ ...online, turn: "black" }, table({ seat: white }))).toBe("friend");
    expect(mover(online, table())).toBe("friend"); // watching
    expect(mover({ ...online, seats: { white: true, black: false } }, table({ seat: white }))).toBe("nobody");
  });

  it("in the tutorial, the player moves until the lesson is done; the AI never does", () => {
    expect(mover({ ...local, turn: "black" }, table({ lesson: { done: false } }))).toBe("me");
    expect(mover(local, table({ lesson: { done: true } }))).toBe("nobody");
  });

  it("nobody moves once the game is over", () => {
    expect(mover({ ...local, winner: "white" }, table())).toBe("nobody");
  });
});

describe("waitingFor", () => {
  it("says what the page is waiting for", () => {
    const white = { color: "white", token: "t" } as const;
    expect(waitingFor({ ...local, turn: "black" }, table(), true)).toBe("AI is thinking…");
    expect(waitingFor(local, table(), true)).toBeNull();
    expect(waitingFor({ ...online, seats: { white: true, black: false } }, table({ seat: white }), false)).toBe(
      "Waiting for your friend to join…",
    );
    expect(waitingFor({ ...online, turn: "black" }, table({ seat: white }), false)).toBe("Waiting for Black to move…");
    expect(waitingFor({ ...online, turn: "black" }, table(), false)).toBeNull(); // spectators aren't waiting
  });
});
