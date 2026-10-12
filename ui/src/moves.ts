// Turning clicks into move notation, driven entirely by the server's legal-move list.

export type Mode = "jump" | "split" | "merge";

export interface ParsedMove {
  type: Mode;
  sources: string[];
  targets: string[];
  promotion?: string;
  notation: string;
}

export function parseMove(notation: string): ParsedMove {
  if (notation.includes("^")) {
    const [left, right] = notation.split("^");
    if (left.length === 2) {
      return { type: "split", sources: [left], targets: [right.slice(0, 2), right.slice(2, 4)], notation };
    }
    return { type: "merge", sources: [left.slice(0, 2), left.slice(2, 4)], targets: [right], notation };
  }
  return {
    type: "jump",
    sources: [notation.slice(0, 2)],
    targets: [notation.slice(2, 4)],
    promotion: notation.length === 5 ? notation[4] : undefined,
    notation,
  };
}

const sameSet = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));

/**
 * The squares that may be clicked next, given the mode and what is already picked.
 * Jump: source, target. Split: source, target, target. Merge: source, source, target.
 */
export function nextSquares(mode: Mode, picked: string[], legal: ParsedMove[]): Set<string> {
  const result = new Set<string>();
  for (const move of legal) {
    if (move.type !== mode) continue;
    const order = [...move.sources, ...move.targets];
    // Splits and merges are symmetric in their pair (b1^a3c3 == b1^c3a3), so match either order.
    const orders =
      mode === "split"
        ? [order, [order[0], order[2], order[1]]]
        : mode === "merge"
          ? [order, [order[1], order[0], order[2]]]
          : [order];
    for (const candidate of orders) {
      if (picked.every((sq, i) => candidate[i] === sq) && candidate.length > picked.length) {
        result.add(candidate[picked.length]);
      }
    }
  }
  return result;
}

/** The legal move completed by ``picked``, if any (queen promotion by default). */
export function completedMove(mode: Mode, picked: string[], legal: ParsedMove[], promotion = "q"): string | null {
  const needed = mode === "jump" ? 2 : 3;
  if (picked.length !== needed) return null;
  for (const move of legal) {
    if (move.type !== mode) continue;
    if (mode === "jump") {
      if (move.sources[0] === picked[0] && move.targets[0] === picked[1]) {
        if (move.promotion === undefined || move.promotion === promotion) return move.notation;
      }
    } else if (mode === "split") {
      if (move.sources[0] === picked[0] && sameSet(move.targets, picked.slice(1))) return move.notation;
    } else if (sameSet(move.sources, picked.slice(0, 2)) && move.targets[0] === picked[2]) {
      return move.notation;
    }
  }
  return null;
}

export const FILES = "abcdefgh";

export function squareIndex(name: string): number {
  return (Number(name[1]) - 1) * 8 + FILES.indexOf(name[0]);
}

export function squareName(index: number): string {
  return FILES[index % 8] + String(Math.floor(index / 8) + 1);
}
