import { LESSONS, type TutorialProgress } from "../tutorial/lessons";
import type { MeasurementInfo } from "../types";
import { describe } from "./MoveLog";

interface TutorialCardProps {
  progress: TutorialProgress;
  lessonsDone: string[];
  /** Measurements made by the player's last move, to explain what nature decided. */
  measurements: MeasurementInfo[];
  busy: boolean;
  onLesson: (index: number) => void;
  onExit: () => void;
}

export function TutorialCard({ progress, lessonsDone, measurements, busy, onLesson, onExit }: TutorialCardProps) {
  const lesson = LESSONS[progress.lesson];
  const step = lesson.steps[progress.step];
  const last = progress.lesson === LESSONS.length - 1;

  return (
    <section className="card tutorial" aria-label="Tutorial">
      <h2>
        Tutorial · lesson {progress.lesson + 1} of {LESSONS.length}
      </h2>
      <ol className="lessons">
        {LESSONS.map((l, i) => (
          <li key={l.id}>
            <button
              type="button"
              className={[i === progress.lesson ? "active" : "", lessonsDone.includes(l.id) ? "done" : ""].join(" ")}
              aria-current={i === progress.lesson ? "step" : undefined}
              title={l.title}
              onClick={() => onLesson(i)}
              disabled={busy}
            >
              {lessonsDone.includes(l.id) ? "✓" : i + 1}
            </button>
          </li>
        ))}
      </ol>
      <h3>{lesson.title}</h3>
      {progress.done ? (
        <>
          <p className="explain">{step.explain}</p>
          {measurements.length > 0 && (
            <ul className="outcomes">
              {measurements.map((m, i) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: a move's measurements never change or reorder
                <li key={i}>⚄ {describe(m)}</li>
              ))}
            </ul>
          )}
        </>
      ) : (
        <p>
          {lesson.steps.length > 1 && (
            <span className="muted">
              Step {progress.step + 1} of {lesson.steps.length}.{" "}
            </span>
          )}
          {step.prompt}
        </p>
      )}
      <div className="buttons">
        <button type="button" onClick={() => onLesson(progress.lesson)} disabled={busy}>
          Restart lesson
        </button>
        {progress.done && !last && (
          <button type="button" className="primary" onClick={() => onLesson(progress.lesson + 1)} disabled={busy}>
            Next lesson
          </button>
        )}
        {progress.done && last ? (
          <button type="button" className="primary" onClick={onExit}>
            Play a real game
          </button>
        ) : (
          <button type="button" onClick={onExit}>
            Exit tutorial
          </button>
        )}
      </div>
    </section>
  );
}
