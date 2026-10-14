"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, getJson, toAnswer } from "@/lib/client";
import { Chat, type Message } from "./Chat";

type Stored = {
  id: string;
  mode: "write" | "review" | "fix";
  market_id: string;
  timeframe: string;
  messages: {
    id: string;
    role: "user" | "assistant";
    content: string;
    code: string | null;
    status: string | null;
    answer: Record<string, unknown> | null;
  }[];
};

/** Opens a saved conversation exactly as it was shown. */
export function ConversationLoader({ id }: { id: string }) {
  const router = useRouter();
  const [stored, setStored] = useState<Stored | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getJson<Stored>(`/api/conversations/${id}`)
      .then(setStored)
      .catch((caught) => {
        if (caught instanceof ApiError && caught.status === 401) router.push("/login");
        else
          setError(
            caught instanceof ApiError && caught.status === 404
              ? "There is no such conversation."
              : "It could not be opened.",
          );
      });
  }, [id, router]);

  if (error) {
    return (
      <p>
        {error} <Link href="/app/history">See your history</Link>
      </p>
    );
  }
  if (!stored) return <p>Opening…</p>;

  const history: Message[] = stored.messages.map((m) =>
    m.role === "user"
      ? {
          role: "user",
          id: m.id,
          text: m.content,
          code: m.code,
          errorText: (m.answer?.error_text as string | undefined) ?? null,
        }
      : {
          role: "assistant",
          id: m.id,
          answer: toAnswer(stored.mode, {
            ...(m.answer ?? {}),
            status: m.status,
            message: m.content,
          }),
          questions: (m.answer?.questions as string[] | undefined) ?? [],
          message: m.content,
        },
  );
  return <Chat conversation={stored} history={history} />;
}
