import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { storage } from "../storage";
import type { Color, LevelInfo, LevelName } from "../types";
import { type Game, isOver } from "./useGame";

/**
 * The AI opponent: which colour it plays, how strong it is, and its moves. It only plays while
 * `active` (ordinary local games, not online games or the tutorial), and answers by itself when
 * it is its turn.
 */
export function useAi(game: Game, active: boolean) {
  const [color, setColor] = useState<Color | null>("black");
  const [levels, setLevels] = useState<LevelInfo[]>([]);
  const [level, setLevel] = useState<LevelName>(() => storage.level() ?? "medium");
  const inFlight = useRef(false);
  const { state, gameId, busy, run, applyResponse } = game;

  /** The colour the AI is playing in this game, if any. */
  const playing = active ? color : null;

  useEffect(() => {
    api
      .levels()
      .then((list) => {
        setLevels(list);
        if (!storage.level()) setLevel(list.find((l) => l.default)?.name ?? "medium");
      })
      .catch(() => setLevels([]));
  }, []);

  const chooseLevel = (name: LevelName) => {
    setLevel(name);
    storage.setLevel(name);
  };

  const move = useCallback(async () => {
    if (!gameId || inFlight.current) return;
    inFlight.current = true;
    await run(async () => {
      try {
        const response = await api.aiMove(gameId, level);
        applyResponse(response, response.search);
      } finally {
        inFlight.current = false; // before run clears busy, so the next turn can start
      }
    });
  }, [gameId, level, run, applyResponse]);

  // Answer automatically when it is the AI's turn.
  useEffect(() => {
    if (state && !isOver(state) && !busy && playing === state.turn) {
      void move();
    }
  }, [state, busy, playing, move]);

  return { color, setColor, playing, levels, level, chooseLevel, move };
}
