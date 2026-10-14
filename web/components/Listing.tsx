import { lines, type Mark } from "@/lib/answer";
import styles from "./Listing.module.css";

type Note = { start: number; end: number; text: string };

const MARK_GLYPH: Record<Mark["kind"], string> = { fail: "✗", tip: "◦", ai: "?" };
const MARK_WORDS: Record<Mark["kind"], string> = {
  fail: "Checker found a problem",
  tip: "Checker suggestion",
  ai: "AI suggestion, not verified",
};

/**
 * Code set as a program listing on green-bar paper. Marks sit in a gutter
 * beside the line they are about; notes sit in the margin beside the lines
 * they explain.
 */
export function Listing({
  code,
  marks = [],
  notes = [],
  label = "Code",
}: {
  code: string;
  marks?: Mark[];
  notes?: Note[];
  label?: string;
}) {
  const rows = lines(code);
  const byLine = new Map<number, Mark[]>();
  for (const mark of marks) {
    if (mark.line >= 1 && mark.line <= rows.length) {
      byLine.set(mark.line, [...(byLine.get(mark.line) ?? []), mark]);
    }
  }
  const placed = notes.filter(
    (note) => note.start >= 1 && note.start <= note.end && note.end <= rows.length,
  );

  return (
    <figure
      className={styles.listing}
      aria-label={label}
      data-has-notes={placed.length > 0 || undefined}
    >
      <div
        className={styles.sheet}
        style={{ gridTemplateRows: `repeat(${rows.length}, var(--line))` }}
      >
        {rows.map((text, index) => {
          const number = index + 1;
          const here = byLine.get(number) ?? [];
          const worst =
            here.find((m) => m.kind === "fail") ?? here.find((m) => m.kind === "ai") ?? here[0];
          return (
            <div
              key={number}
              className={styles.row}
              style={{ gridRow: number }}
              data-band={Math.floor(index / 3) % 2 === 0 || undefined}
              data-mark={worst?.kind}
            >
              <span className={styles.number} aria-hidden="true">
                {number}
              </span>
              <span className={styles.gutter}>
                {worst ? (
                  <span
                    className={styles.mark}
                    data-kind={worst.kind}
                    title={here.map((m) => m.text).join("\n")}
                  >
                    <span aria-hidden="true">{MARK_GLYPH[worst.kind]}</span>
                    <span className="visually-hidden">
                      {MARK_WORDS[worst.kind]} on line {number}: {here.map((m) => m.text).join(" ")}
                    </span>
                  </span>
                ) : null}
              </span>
              <code className={styles.code}>{text || " "}</code>
            </div>
          );
        })}
        {placed.map((note) => (
          <p
            key={`${note.start}-${note.end}`}
            className={styles.note}
            style={{ gridRow: `${note.start} / ${note.end + 1}` }}
          >
            <span className={styles.noteLines}>
              {note.start === note.end ? `Line ${note.start}` : `Lines ${note.start}–${note.end}`}
            </span>{" "}
            {note.text}
          </p>
        ))}
      </div>
    </figure>
  );
}
