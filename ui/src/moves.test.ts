import { describe, expect, it } from "vitest";
import { completedMove, nextSquares, parseMove, squareIndex, squareName } from "./moves";

const legal = ["e2e4", "e2e3", "g1f3", "g1h3", "g1^f3h3", "b1^a3c3", "a3c3^b1", "a3c3^b5", "a7a8q", "a7a8n"].map(
  parseMove,
);

describe("parseMove", () => {
  it("parses all move types", () => {
    expect(parseMove("b1^a3c3")).toMatchObject({ type: "split", sources: ["b1"], targets: ["a3", "c3"] });
    expect(parseMove("a3c3^b1")).toMatchObject({ type: "merge", sources: ["a3", "c3"], targets: ["b1"] });
    expect(parseMove("a7a8q")).toMatchObject({ type: "jump", promotion: "q" });
  });
});

describe("nextSquares", () => {
  it("offers sources, then targets, for a jump", () => {
    expect(nextSquares("jump", [], legal)).toEqual(new Set(["e2", "g1", "a7"]));
    expect(nextSquares("jump", ["g1"], legal)).toEqual(new Set(["f3", "h3"]));
  });

  it("accepts split targets in either order", () => {
    expect(nextSquares("split", ["g1"], legal)).toEqual(new Set(["f3", "h3"]));
    expect(nextSquares("split", ["g1", "h3"], legal)).toEqual(new Set(["f3"]));
  });

  it("accepts merge sources in either order", () => {
    expect(nextSquares("merge", [], legal)).toEqual(new Set(["a3", "c3"]));
    expect(nextSquares("merge", ["c3", "a3"], legal)).toEqual(new Set(["b1", "b5"]));
  });
});

describe("completedMove", () => {
  it("completes moves and normalises order", () => {
    expect(completedMove("jump", ["e2", "e4"], legal)).toBe("e2e4");
    expect(completedMove("split", ["g1", "h3", "f3"], legal)).toBe("g1^f3h3");
    expect(completedMove("merge", ["c3", "a3", "b5"], legal)).toBe("a3c3^b5");
    expect(completedMove("jump", ["e2"], legal)).toBeNull();
  });

  it("uses the chosen promotion", () => {
    expect(completedMove("jump", ["a7", "a8"], legal)).toBe("a7a8q");
    expect(completedMove("jump", ["a7", "a8"], legal, "n")).toBe("a7a8n");
  });
});

describe("square names", () => {
  it("round-trips", () => {
    for (let i = 0; i < 64; i++) expect(squareIndex(squareName(i))).toBe(i);
    expect(squareIndex("h8")).toBe(63);
  });
});
