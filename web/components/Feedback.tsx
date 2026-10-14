"use client";

import { useState } from "react";
import { postJson } from "@/lib/client";
import styles from "./Chat.module.css";

/** Thumbs up or down on one answer, with an optional comment on a thumbs down. */
export function Feedback({ messageId }: { messageId: string }) {
  const [rating, setRating] = useState<1 | -1 | null>(null);
  const [comment, setComment] = useState("");
  const [sent, setSent] = useState(false);

  async function send(value: 1 | -1, text?: string) {
    setRating(value);
    await postJson(`/api/messages/${messageId}/feedback`, {
      rating: value,
      comment: text || null,
    }).catch(() => {});
    setSent(value === 1 || text !== undefined);
  }

  return (
    <div className={styles.feedback}>
      <span>Was this answer right?</span>
      <button
        type="button"
        aria-pressed={rating === 1}
        onClick={() => send(1)}
        className={styles.thumb}
      >
        Yes
      </button>
      <button
        type="button"
        aria-pressed={rating === -1}
        onClick={() => send(-1)}
        className={styles.thumb}
      >
        No
      </button>
      {rating === -1 && !sent ? (
        <form
          className={styles.comment}
          onSubmit={(event) => {
            event.preventDefault();
            send(-1, comment);
          }}
        >
          <label>
            What was wrong?
            <input value={comment} onChange={(e) => setComment(e.target.value)} maxLength={2000} />
          </label>
          <button type="submit" className={styles.thumb}>
            Send
          </button>
        </form>
      ) : null}
      {sent ? <span className={styles.thanks}>Thank you. It helps us fix mistakes.</span> : null}
    </div>
  );
}
