// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import split from "./fixtures/split.json";
import { LESSONS } from "./tutorial/lessons";
import type { GameState } from "./types";

// A start-like position (white to move, nothing played) to build responses from.
const base: GameState = { ...(split.state as GameState), turn: "white", history: [], seats: null };

type Route = (url: string, body: Record<string, unknown> | null) => unknown;

/** Stub fetch with a router; returns the recorded calls. Unrouted requests stay pending. */
function serve(route: Route) {
  const calls: { url: string; body: Record<string, unknown> | null }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      calls.push({ url, body });
      const result = route(url, body);
      if (result === undefined) return new Promise(() => {});
      if (result instanceof Response) return Promise.resolve(result);
      return Promise.resolve(new Response(JSON.stringify(result), { status: 200 }));
    }),
  );
  return calls;
}

class FakeSocket {
  static OPEN = 1;
  static instances: FakeSocket[] = [];
  readyState = 1;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
    queueMicrotask(() => this.onopen?.());
  }
  send() {}
  close() {}
  emit(message: unknown) {
    act(() => this.onmessage?.({ data: JSON.stringify(message) }));
  }
}

const square = (name: string) => screen.getByRole("button", { name: new RegExp(`^${name}( |$)`) });

async function renderApp() {
  await act(async () => {
    render(<App />);
  });
}

beforeEach(() => {
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  window.history.replaceState(null, "", "/");
});

describe("tutorial", () => {
  it("only allows the lesson's move, then explains it and remembers the lesson", async () => {
    const lesson = LESSONS[0];
    const calls = serve((url) => {
      if (url.startsWith("/init")) return { ...base, game_id: "lesson" };
      if (url.startsWith("/legal_moves")) return { moves: ["a1a8", "e2e4", "b1c3"] };
      if (url.startsWith("/levels")) return [];
      if (url.startsWith("/do_move"))
        return {
          move: "a1a8",
          executed: true,
          captured: "k",
          measurements: [],
          state: { ...base, game_id: "lesson", turn: "black", winner: "white", history: [{ notation: "a1a8", executed: true, outcomes: [] }] },
        };
    });
    await renderApp();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Learn to play" }));
    });
    expect(calls.find((c) => c.url === "/init" && c.body?.fen === lesson.fen)).toBeTruthy();
    expect(screen.getByText(lesson.steps[0].prompt)).toBeTruthy();
    expect(square("a1").classList.contains("selectable")).toBe(true);
    expect(square("e2").classList.contains("selectable")).toBe(false); // legal, but not this lesson

    await act(async () => {
      fireEvent.click(square("a1"));
    });
    await act(async () => {
      fireEvent.click(square("a8"));
    });
    expect(calls.find((c) => c.url === "/do_move")?.body?.notation).toBe("a1a8");
    expect(screen.getByText(lesson.steps[0].explain!)).toBeTruthy();
    expect(JSON.parse(localStorage.getItem("quantum-chess:tutorial-done")!)).toEqual([lesson.id]);
    expect(screen.getByRole("button", { name: "Next lesson" })).toBeTruthy();
  });
});

describe("online play", () => {
  it("creates an invite, waits for the friend, sends the seat token and follows the feed", async () => {
    localStorage.setItem("quantum-chess:game-id", "local");
    const online = { ...base, game_id: "g1", seats: { white: true, black: false } };
    const afterMove = {
      ...online,
      seats: { white: true, black: true },
      turn: "black",
      history: [{ notation: "e2e4", executed: true, outcomes: [] }],
    };
    const calls = serve((url) => {
      if (url.startsWith("/state")) return { ...base, game_id: "local" };
      if (url.startsWith("/levels")) return [];
      if (url.startsWith("/legal_moves")) return { moves: ["e2e4"] };
      if (url.startsWith("/online/create")) return { game_id: "g1", color: "white", token: "secret", state: online };
      if (url.startsWith("/do_move")) return { move: "e2e4", executed: true, captured: null, measurements: [], state: afterMove };
    });
    await renderApp();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Create invite link" }));
    });
    expect((screen.getByLabelText("Invite link") as HTMLInputElement).value).toContain("?join=g1");
    expect(screen.getByRole("status").textContent).toContain("Waiting for your friend to join");
    expect(JSON.parse(localStorage.getItem("quantum-chess:seat:g1")!)).toEqual({ color: "white", token: "secret" });
    expect(window.location.search).toBe("?game=g1");
    expect(screen.queryByRole("button", { name: "AI move now" })).toBeNull();

    const socket = FakeSocket.instances.at(-1)!;
    expect(socket.url).toContain("/ws?game_id=g1");
    socket.emit({ type: "state", state: { ...online, seats: { white: true, black: true } } });
    expect(screen.getByRole("status").textContent).toContain("White to move (you)");

    await act(async () => {
      fireEvent.click(square("e2"));
    });
    await act(async () => {
      fireEvent.click(square("e4"));
    });
    expect(calls.find((c) => c.url === "/do_move")?.body).toMatchObject({ notation: "e2e4", token: "secret" });
    expect(screen.getByRole("status").textContent).toContain("Waiting for Black to move");

    // The feed echoes our own move (ignored), then brings the friend's reply.
    socket.emit({ type: "move", move: "e2e4", executed: true, captured: null, measurements: [], state: afterMove });
    socket.emit({
      type: "move",
      move: "e7e5",
      executed: true,
      captured: null,
      measurements: [],
      state: { ...afterMove, turn: "white", history: [...afterMove.history, { notation: "e7e5", executed: true, outcomes: [] }] },
    });
    const logged = screen.getAllByText(/^e[27]e[45]$/).map((el) => el.textContent);
    expect(logged).toEqual(["e2e4", "e7e5"]);
  });

  it("joins from an invite link as black, with the board turned around", async () => {
    window.history.replaceState(null, "", "/?join=g2");
    const joined = { ...base, game_id: "g2", seats: { white: true, black: true } };
    const calls = serve((url) => {
      if (url.startsWith("/online/join")) return { game_id: "g2", color: "black", token: "t2", state: joined };
      if (url.startsWith("/levels")) return [];
      if (url.startsWith("/legal_moves")) return { moves: [] };
    });
    await renderApp();
    expect(calls.find((c) => c.url === "/online/join")?.body).toEqual({ game_id: "g2" });
    expect(JSON.parse(localStorage.getItem("quantum-chess:seat:g2")!)).toEqual({ color: "black", token: "t2" });
    expect(window.location.search).toBe("?game=g2");
    const squares = screen.getAllByRole("button", { name: /^[a-h][1-8]/ });
    expect(squares[0].getAttribute("aria-label")).toMatch(/^h1/);
    expect(screen.getByRole("status").textContent).toContain("Waiting for White to move");
  });

  it("watches when both seats are taken", async () => {
    window.history.replaceState(null, "", "/?join=g3");
    serve((url) => {
      if (url.startsWith("/online/join")) return new Response(JSON.stringify({ detail: "both seats are taken" }), { status: 409 });
      if (url.startsWith("/state")) return { ...base, game_id: "g3", seats: { white: true, black: true } };
      if (url.startsWith("/levels")) return [];
      if (url.startsWith("/legal_moves")) return { moves: ["e2e4"] };
    });
    await renderApp();
    expect(screen.getByText("Both seats are taken, so you are watching this game.")).toBeTruthy();
    expect(screen.getByText(/^You are watching this game./)).toBeTruthy();
    expect(square("e2").classList.contains("selectable")).toBe(false);
  });
});
