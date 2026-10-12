import type { Correlations, GameState, Kind, PieceInfo } from "../types";
import { FILES, squareIndex, squareName } from "../moves";

// U+FE0E asks for the text glyph: without it, some systems draw ♟ as a colour emoji.
const GLYPHS: Record<Kind, string> = {
  king: "♚︎",
  queen: "♛︎",
  rook: "♜︎",
  bishop: "♝︎",
  knight: "♞︎",
  pawn: "♟︎",
};

export const GROUP_COLORS = ["#7c5cff", "#ff8a3d", "#16b8a6", "#e8508a", "#3d9bff", "#c9a400"];

interface BoardProps {
  state: GameState;
  flipped: boolean;
  selectable: Set<string>;
  picked: string[];
  lastMove: string[];
  flashing: Set<string>;
  correlations: Correlations | null;
  onClick: (square: string) => void;
  onHover: (square: string | null) => void;
}

const percent = (p: number) => `${Math.round(p * 100)}%`;

export function Board(props: BoardProps) {
  const { state, flipped, selectable, picked, lastMove, flashing, correlations } = props;

  const pieces = new Map<string, PieceInfo>(state.pieces.map((p) => [p.square, p]));
  const groupOf = new Map<string, number>();
  state.entanglement_groups.forEach((group, i) => group.forEach((sq) => groupOf.set(sq, i)));

  const ranks = flipped ? [0, 1, 2, 3, 4, 5, 6, 7] : [7, 6, 5, 4, 3, 2, 1, 0];
  const files = flipped ? [7, 6, 5, 4, 3, 2, 1, 0] : [0, 1, 2, 3, 4, 5, 6, 7];

  return (
    <div className="board-wrap">
      <div className="board" role="grid" aria-label="Quantum chess board">
        {ranks.map((rank) =>
          files.map((file) => {
            const sq = squareName(rank * 8 + file);
            const piece = pieces.get(sq);
            const p = state.probabilities[squareIndex(sq)];
            const group = groupOf.get(sq);
            const uncertain = p > 0 && p < 1;
            // Once a piece is picked, the squares it can go to get a dot (empty) or a ring (occupied).
            const target = picked.length > 0 && selectable.has(sq);
            const ifOccupied = correlations?.if_occupied[sq];
            const ifEmpty = correlations?.if_empty[sq];
            const classes = [
              "square",
              (rank + file) % 2 === 0 ? "dark" : "light",
              selectable.has(sq) ? "selectable" : "",
              uncertain ? "superposed" : "",
              picked.includes(sq) ? "picked" : "",
              lastMove.includes(sq) ? "last" : "",
              flashing.has(sq) ? "flash" : "",
              sq in state.check ? "check" : "",
              correlations?.square === sq ? "hovered" : "",
            ];
            return (
              <button
                key={sq}
                className={classes.join(" ")}
                style={group !== undefined ? { ["--ring" as string]: GROUP_COLORS[group % GROUP_COLORS.length] } : {}}
                data-group={group !== undefined ? "" : undefined}
                onClick={() => props.onClick(sq)}
                onMouseEnter={() => props.onHover(uncertain ? sq : null)}
                onMouseLeave={() => props.onHover(null)}
                aria-label={`${sq}${piece ? ` ${piece.color} ${piece.kind} ${percent(p)}` : ""}`}
              >
                {target && <span className={piece ? "hint capture" : "hint"} />}
                {piece && (
                  <span
                    className={`piece ${piece.color}`}
                    style={{ opacity: uncertain ? 0.3 + 0.7 * p : 1 }}
                  >
                    {GLYPHS[piece.kind]}
                  </span>
                )}
                {uncertain && <span className="prob">{percent(p)}</span>}
                {uncertain && (
                  <span className="bar">
                    <span style={{ width: percent(p) }} />
                  </span>
                )}
                {ifOccupied !== undefined && ifEmpty !== undefined && (
                  <span className="conditional">
                    <span title="if the hovered square is occupied">● {percent(ifOccupied)}</span>
                    <span title="if the hovered square is empty">○ {percent(ifEmpty)}</span>
                  </span>
                )}
                {file === (flipped ? 7 : 0) && <span className="coord rank">{rank + 1}</span>}
                {rank === (flipped ? 7 : 0) && <span className="coord file">{FILES[file]}</span>}
              </button>
            );
          }),
        )}
      </div>
    </div>
  );
}
