import { useState } from "react";
import { api } from "../api";
import type { Mode } from "../moves";
import { storage } from "../storage";
import { LESSONS, type TutorialProgress } from "../tutorial/lessons";
import { type Game, setUrlGame } from "./useGame";

const REPLY_DELAY_MS = 600; // let the player see their move before a tutorial reply

/**
 * The tutorial: the lesson in progress and the lessons finished. Each lesson plays on its own
 * game; `setMode` switches the move type to the one the current step asks for.
 */
export function useTutorial(game: Game, setMode: (mode: Mode) => void) {
  const [progress, setProgress] = useState<TutorialProgress | null>(null);
  const [lessonsDone, setLessonsDone] = useState<string[]>(() => storage.lessonsDone());
  const { run, showGame, applyResponse } = game;

  const step = progress ? LESSONS[progress.lesson].steps[progress.step] : null;

  const start = (index: number) =>
    run(async () => {
      const lesson = LESSONS[index];
      const fresh = await api.init(lesson.fen);
      setUrlGame(null);
      game.setNotice(null);
      game.setFlipped(false);
      showGame(fresh, []);
      for (const notation of lesson.setup ?? []) applyResponse(await api.move(fresh.game_id, notation));
      setProgress({ lesson: index, step: 0, done: false });
      setMode(lesson.steps[0].mode);
    });

  /** Back to the game played before the tutorial. */
  const exit = () => {
    setProgress(null);
    const stored = storage.gameId();
    void run(() => (stored ? game.resume(stored) : game.newGame()));
  };

  /** After the player's move: play the lesson's reply and go to the next step, or finish. */
  const advance = async (gameId: string) => {
    if (!progress) return;
    const lesson = LESSONS[progress.lesson];
    const current = lesson.steps[progress.step];
    if (progress.step + 1 < lesson.steps.length) {
      if (current.reply) {
        await new Promise((resolve) => window.setTimeout(resolve, REPLY_DELAY_MS));
        applyResponse(await api.move(gameId, current.reply));
      }
      setProgress({ ...progress, step: progress.step + 1 });
      setMode(lesson.steps[progress.step + 1].mode);
      return;
    }
    setProgress({ ...progress, done: true });
    if (!lessonsDone.includes(lesson.id)) {
      const done = [...lessonsDone, lesson.id];
      setLessonsDone(done);
      storage.setLessonsDone(done);
    }
  };

  return { progress, step, lessonsDone, start, exit, advance };
}
