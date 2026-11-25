import { describe, expect, it } from "vitest";
import { gameAddress, inviteLink, readLink } from "./links";

// The same examples as tests/test_links.py, which checks the Python side of these formats.
describe("readLink", () => {
  it("reads games, invitations and handed-over seats", () => {
    expect(readLink({ search: "?game=abc", hash: "" })).toEqual({ game: "abc", join: null, seat: null });
    expect(readLink({ search: "?join=abc", hash: "" })).toEqual({ game: null, join: "abc", seat: null });
    expect(readLink({ search: "?game=abc", hash: "#seat=black.tok.en" })).toEqual({
      game: "abc",
      join: null,
      seat: { color: "black", token: "tok.en" },
    });
  });

  it("ignores a seat without a game, or for no real colour", () => {
    expect(readLink({ search: "", hash: "#seat=white.t" }).seat).toBeNull();
    expect(readLink({ search: "?game=abc", hash: "#seat=red.t" }).seat).toBeNull();
  });
});

describe("building links", () => {
  const here = { origin: "http://localhost:8000", pathname: "/" };

  it("invites on this page, or on a hosting address", () => {
    expect(inviteLink("abc", null, here)).toBe("http://localhost:8000/?join=abc");
    expect(inviteLink("abc", "http://192.168.1.20:5555/", here)).toBe("http://192.168.1.20:5555/?join=abc");
  });

  it("points the address bar at a game, or at the bare page", () => {
    expect(gameAddress("a b", "/")).toBe("?game=a%20b");
    expect(gameAddress(null, "/app/")).toBe("/app/");
  });
});
