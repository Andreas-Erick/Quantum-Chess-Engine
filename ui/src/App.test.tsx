// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import legal from "./fixtures/legal-moves.json";
import split from "./fixtures/split.json";

const levels = [
  { name: "easy", label: "Easy", description: "Easy one.", default: false },
  { name: "medium", label: "Medium", description: "Medium one.", default: true },
  { name: "hard", label: "Hard", description: "Hard one.", default: false },
];

function json(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
}

describe("App with a superposed knight", () => {
  beforeEach(() => {
    localStorage.setItem("quantum-chess:game-id", split.state.game_id);
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url.startsWith("/state")) return json(split.state);
        if (url.startsWith("/legal_moves")) return json(legal);
        if (url.startsWith("/levels")) return json(levels);
        return new Promise(() => {}); // AI move: leave pending
      }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("renders probabilities and entanglement rings", async () => {
    await act(async () => {
      render(<App />);
    });
    const f3 = await screen.findByRole("button", { name: /^f3 white knight 50%/ });
    expect(f3.textContent).toContain("50%");
    expect(f3.hasAttribute("data-group")).toBe(true);
  });

  it("shows strength levels, defaults to the server's default and remembers a choice", async () => {
    await act(async () => {
      render(<App />);
    });
    const medium = await screen.findByRole("radio", { name: "Medium" });
    expect(medium.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText("Medium one.")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "Hard" }));
    expect(screen.getByRole("radio", { name: "Hard" }).getAttribute("aria-checked")).toBe("true");
    expect(localStorage.getItem("quantum-chess:level")).toBe("hard");
  });

  it("marks where a picked piece can go with its own element, not the square's ::before", async () => {
    // The last-move highlight uses ::before; a target dot sharing it was pinned to the corner.
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url.startsWith("/state")) return json({ ...split.state, turn: "white" });
        if (url.startsWith("/legal_moves")) return json({ moves: ["b1a3", "b1c3", "e2e4"] });
        if (url.startsWith("/levels")) return json(levels);
        return new Promise(() => {});
      }),
    );
    await act(async () => {
      render(<App />);
    });
    fireEvent.click(await screen.findByRole("button", { name: /^b1 / }));
    for (const name of ["a3", "c3"]) {
      expect(screen.getByRole("button", { name: new RegExp(`^${name}$`) }).querySelector(".hint")).not.toBeNull();
    }
    expect(screen.getByRole("button", { name: /^e4$/ }).querySelector(".hint")).toBeNull();
  });
});
