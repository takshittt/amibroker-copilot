import { notFound } from "next/navigation";
import { AnswerView } from "@/components/Answer";
import { CHECKED, NOT_FULLY_CHECKED, REVIEW } from "@/lib/fixtures";

/** Design preview of the three kinds of answer. Development only. */
export default function Preview() {
  if (process.env.NODE_ENV === "production") notFound();
  return (
    <main
      style={{
        maxWidth: "82rem",
        margin: "0 auto",
        padding: "2rem var(--gutter)",
        display: "grid",
        gap: "4rem",
      }}
    >
      <AnswerView answer={CHECKED} />
      <AnswerView answer={NOT_FULLY_CHECKED} />
      <AnswerView answer={REVIEW} />
    </main>
  );
}
