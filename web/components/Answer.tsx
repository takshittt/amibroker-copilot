import { checkName, headline, marks } from "@/lib/answer";
import type { Answer, CodeAnswer, Finding, ReviewAnswer } from "@/lib/types";
import styles from "./Answer.module.css";
import { CopyButton } from "./CopyButton";
import { Listing } from "./Listing";

/** One answer: what was checked, the code, and everything that goes with it. */
export function AnswerView({
  answer,
  actions,
  reviewedCode,
}: {
  answer: Answer;
  actions?: React.ReactNode;
  /** For a review: the code that was reviewed, shown with its marks. */
  reviewedCode?: string | null;
}) {
  const shown = headline(answer);
  return (
    <article className={styles.answer} data-tone={shown.tone}>
      {shown.title ? (
        <header className={styles.status} data-tone={shown.tone}>
          <p className={styles.statusTitle}>{shown.title}</p>
          <p className={styles.statusDetail}>{shown.detail}</p>
        </header>
      ) : null}
      {answer.kind === "review" ? (
        <ReviewBody answer={answer} code={reviewedCode} />
      ) : (
        <CodeBody answer={answer} />
      )}
      {answer.notes.length > 0 ? (
        <section className={styles.notes} aria-label="Notes">
          {answer.notes.map((note) => (
            <p key={note}>{note}</p>
          ))}
        </section>
      ) : null}
      {actions ? <footer className={styles.actions}>{actions}</footer> : null}
    </article>
  );
}

function CodeBody({ answer }: { answer: CodeAnswer }) {
  const notes = (answer.explanation ?? []).map((b) => ({
    start: b.start_line,
    end: b.end_line,
    text: b.text,
  }));
  const changes = (answer.changes ?? [])
    .filter((c) => c.line > 0)
    .map((c) => ({ start: c.line, end: c.line, text: c.text }));
  return (
    <>
      {answer.problems.length > 0 ? <ProblemList answer={answer} /> : null}
      <div className={styles.codeBlock}>
        <Listing code={answer.code} marks={marks(answer)} notes={[...notes, ...changes]} />
        <div className={styles.codeTools}>
          <CopyButton text={answer.code} />
        </div>
      </div>
      {notes.length > 0 ? (
        <section className={styles.explainNarrow} aria-label="What the code does">
          <h3 className={styles.heading}>What it does</h3>
          <ul>
            {notes.map((note) => (
              <li key={`${note.start}-${note.end}`}>
                <strong>
                  {note.start === note.end
                    ? `Line ${note.start}`
                    : `Lines ${note.start}–${note.end}`}
                </strong>{" "}
                {note.text}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <div className={styles.lower}>
        <Checks answer={answer} />
        {answer.doc_links.length > 0 ? (
          <section aria-label="AmiBroker documentation">
            <h3 className={styles.heading}>In the AmiBroker reference</h3>
            <ul className={styles.docs}>
              {answer.doc_links.map((link) => (
                <li key={link.name}>
                  <a href={link.url} target="_blank" rel="noreferrer">
                    <code>{link.name}</code>
                  </a>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </>
  );
}

function ProblemList({ answer }: { answer: CodeAnswer }) {
  return (
    <ul className={styles.problems} aria-label="What still fails">
      {answer.problems.map((p) => (
        <li key={`${p.rule}-${p.line}-${p.message}`}>
          <span className={styles.where}>{p.line ? `Line ${p.line}` : "Whole code"}</span>
          <span>
            {p.message}
            {p.fix ? <span className={styles.fix}> {p.fix}</span> : null}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Checks({ answer }: { answer: { checks: { name: string; outcome: string }[] } }) {
  if (answer.checks.length === 0) return null;
  return (
    <section className={styles.slip} aria-label="Checks">
      <h3 className={styles.heading}>Verified by the checker</h3>
      <ul>
        {answer.checks.map((check) => (
          <li key={check.name} data-outcome={check.outcome}>
            <span className={styles.tick} aria-hidden="true">
              {check.outcome === "passed" ? "✓" : check.outcome === "failed" ? "✗" : "–"}
            </span>
            <span>
              {checkName(check.name)}
              <span className="visually-hidden">: {check.outcome}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function ReviewBody({ answer, code }: { answer: ReviewAnswer; code?: string | null }) {
  const verified = answer.findings.filter((f) => f.label === "Verified");
  const ai = answer.findings.filter((f) => f.label === "AI-suggested");
  return (
    <>
      {code ? (
        <Listing code={code} marks={marks(answer)} label="Your code, with the findings marked" />
      ) : null}
      <div className={styles.findingGroups}>
        <FindingGroup
          title="Verified by the checker"
          intro="Found by fixed rules. These are certain."
          findings={verified}
          kind="verified"
          empty="The checker found nothing."
        />
        <FindingGroup
          title="Suggested by the AI review"
          intro="Read these as a second opinion. Nothing here is verified."
          findings={ai}
          kind="ai"
          empty={
            answer.ai_review === "failed"
              ? "The AI review could not be completed."
              : "The AI review found nothing."
          }
        />
      </div>
      {answer.summary ? <p className={styles.summary}>{answer.summary}</p> : null}
      <div className={styles.lower}>
        <Checks answer={answer} />
      </div>
    </>
  );
}

function FindingGroup({
  title,
  intro,
  findings,
  kind,
  empty,
}: {
  title: string;
  intro: string;
  findings: Finding[];
  kind: "verified" | "ai";
  empty: string;
}) {
  return (
    <section className={styles.group} data-kind={kind} aria-label={title}>
      <h3 className={styles.heading}>{title}</h3>
      <p className={styles.groupIntro}>{intro}</p>
      {findings.length === 0 ? (
        <p className={styles.empty}>{empty}</p>
      ) : (
        <ul>
          {findings.map((f) => (
            <li key={`${f.line}-${f.message}`} data-severity={f.severity}>
              <span className={styles.where}>{f.line ? `Line ${f.line}` : "Whole code"}</span>
              <span className={styles.findingText}>
                {f.message}
                {f.fix ? <span className={styles.fix}> {f.fix}</span> : null}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
