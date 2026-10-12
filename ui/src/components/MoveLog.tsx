import { useEffect, useRef } from "react";
import type { Color, MeasurementInfo, SearchInfo } from "../types";

export interface LogEntry {
  ply: number;
  color: Color;
  notation: string;
  executed: boolean;
  captured: string | null;
  measurements: MeasurementInfo[] | null; // null when restored from history (details unknown)
  outcomes: boolean[];
  search?: SearchInfo;
}

const percent = (p: number) => `${Math.round(p * 100)}%`;

export function describe(m: MeasurementInfo): string {
  const collapsed = Object.keys(m.collapsed).length;
  const chain = collapsed > 1 ? ` · ${collapsed} squares collapsed` : "";
  if (m.kind === "path") {
    return `path ${m.squares.join(" ")} clear? (${percent(m.probability)}) → ${m.outcome ? "clear" : "blocked"}${chain}`;
  }
  return `${m.squares[0]} occupied? (${percent(m.probability)}) → ${m.outcome ? "yes" : "no"}${chain}`;
}

export function MoveLog({ entries }: { entries: LogEntry[] }) {
  const list = useRef<HTMLOListElement>(null);
  // Keep the newest move in view by scrolling the list itself, not the page. The block body
  // matters: an effect must not return anything but a cleanup function.
  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll whenever a move is added
  useEffect(() => {
    const el = list.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [entries.length]);

  if (entries.length === 0) {
    return <p className="muted">No moves yet. White to play.</p>;
  }
  return (
    <ol className="log" ref={list}>
      {entries.map((e) => (
        <li key={e.ply} className={e.executed ? "" : "failed"}>
          <div className="log-head">
            <span className={`dot ${e.color}`} role="img" aria-label={e.color} />
            <code>{e.notation}</code>
            {e.captured && <span className="tag capture">×{e.captured}</span>}
            {!e.executed && <span className="tag fail">failed</span>}
            {e.search && <span className="tag ai">AI · {e.search.iterations} it</span>}
          </div>
          {e.measurements
            ? e.measurements.map((m, i) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: a move's measurements never change or reorder
                <div key={i} className="measure">
                  ⚄ {describe(m)}
                </div>
              ))
            : e.outcomes.length > 0 && (
                <div className="measure">⚄ outcomes: {e.outcomes.map((o) => (o ? "yes" : "no")).join(", ")}</div>
              )}
        </li>
      ))}
    </ol>
  );
}
