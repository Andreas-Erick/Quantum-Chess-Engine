// Interactive lessons. Each runs on a real engine game: the player may make only the moves a step
// accepts, and tests/test_tutorial.py replays every lesson on the engine so they stay playable.

import type { Mode } from "../moves";
import data from "./lessons.json";

export interface LessonStep {
  mode: Mode;
  /** Notation prefixes: a legal move is accepted if it starts with one of them. */
  accept: string[];
  prompt: string;
  /** The opponent's scripted answer, played before the next step. */
  reply?: string;
  /** Shown once the step is played; the last step of a lesson always has one. */
  explain?: string;
}

export interface Lesson {
  id: string;
  title: string;
  fen: string;
  /** Moves played automatically before the first step. */
  setup?: string[];
  steps: LessonStep[];
}

export const LESSONS = data as Lesson[];

export const accepts = (step: LessonStep, notation: string) =>
  step.accept.some((prefix) => notation.startsWith(prefix));

/** Where the player is in the tutorial. `done` means the lesson's last step has been played. */
export interface TutorialProgress {
  lesson: number;
  step: number;
  done: boolean;
}
