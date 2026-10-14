"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ApiError, getJson, postJson, postStream, stageName, toAnswer } from "@/lib/client";
import type { Answer } from "@/lib/types";
import { useReady } from "@/lib/useReady";
import { AnswerView } from "./Answer";
import styles from "./Chat.module.css";
import { Feedback } from "./Feedback";
import { USAGE_CHANGED } from "./UsageMeter";

type Mode = "write" | "review" | "fix";
type Market = { id: string; name: string };
type Conversation = { id: string; mode: Mode; market_id: string; timeframe: string };

export type Message =
  | { role: "user"; id: string; text: string; code?: string | null; errorText?: string | null }
  | { role: "assistant"; id: string; answer: Answer; questions?: string[]; message?: string };

const TIMEFRAMES = [
  "1min",
  "3min",
  "5min",
  "10min",
  "15min",
  "30min",
  "hourly",
  "daily",
  "weekly",
  "monthly",
];
const MODES: { id: Mode; name: string; action: string }[] = [
  { id: "write", name: "Write", action: "Write the code" },
  { id: "review", name: "Review", action: "Review the code" },
  { id: "fix", name: "Fix an error", action: "Fix the code" },
];

let localId = 0;
const nextId = () => `local-${++localId}`;

export function Chat({
  conversation: initial,
  history = [],
}: {
  conversation?: Conversation;
  history?: Message[];
}) {
  const router = useRouter();
  const [conversation, setConversation] = useState<Conversation | undefined>(initial);
  const [mode, setMode] = useState<Mode>(initial?.mode ?? "write");
  const [marketId, setMarketId] = useState(initial?.market_id ?? "nse_fo");
  const [timeframe, setTimeframe] = useState(initial?.timeframe ?? "5min");
  const [markets, setMarkets] = useState<Market[]>([]);
  const [messages, setMessages] = useState<Message[]>(history);
  const [stages, setStages] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [text, setText] = useState("");
  const [code, setCode] = useState("");
  const [errorText, setErrorText] = useState("");
  const abort = useRef<AbortController | null>(null);
  const ready = useReady();

  useEffect(() => {
    getJson<Market[]>("/api/markets")
      .then(setMarkets)
      .catch((caught) => {
        if (caught instanceof ApiError && caught.status === 401) router.push("/login");
      });
    return () => abort.current?.abort();
  }, [router]);

  const started = conversation !== undefined;
  const lastAnswer = [...messages].reverse().find((m) => m.role === "assistant");
  const awaitingReply = lastAnswer?.role === "assistant" && lastAnswer.answer.status === "clarify";

  async function run(path: string, body: unknown, convMode: Mode) {
    setBusy(true);
    setError("");
    setStages([]);
    abort.current = new AbortController();
    try {
      const final = await postStream(
        path,
        body,
        (stage) => setStages((seen) => [...seen, stage]),
        abort.current.signal,
      );
      const data = final.data;
      if (final.event === "error" && !("status" in data)) {
        setError(String(data.message ?? "Something went wrong. Please try again."));
      } else {
        const answer = toAnswer(convMode, data);
        setMessages((seen) => [
          ...seen,
          {
            role: "assistant",
            id: String(data.message_id ?? nextId()),
            answer,
            questions: (data.questions as string[] | undefined) ?? [],
            message: String(data.message ?? ""),
          },
        ]);
      }
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        router.push("/login");
        return;
      }
      if ((caught as Error).name !== "AbortError") {
        setError(
          caught instanceof ApiError
            ? caught.message
            : "The connection was lost. Please try again.",
        );
      }
    } finally {
      setBusy(false);
      setStages([]);
      window.dispatchEvent(new Event(USAGE_CHANGED));
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    let current = conversation;
    try {
      if (!current) {
        current = await postJson<Conversation>("/api/conversations", {
          mode,
          market_id: marketId,
          timeframe,
        });
        setConversation(current);
        // Keep the address of this conversation without reloading the page.
        window.history.replaceState(null, "", `/app/c/${current.id}`);
      }
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "Something went wrong. Please try again.",
      );
      return;
    }
    const body =
      current.mode === "write"
        ? { text }
        : current.mode === "review"
          ? { text, code }
          : { text, code, error_text: errorText };
    setMessages((seen) => [
      ...seen,
      { role: "user", id: nextId(), text, code: body.code, errorText: body.error_text },
    ]);
    setText("");
    setCode("");
    setErrorText("");
    await run(`/api/conversations/${current.id}/messages`, body, current.mode);
  }

  async function applyFixes(messageId: string) {
    await run(`/api/messages/${messageId}/apply-fixes`, undefined, "review");
  }

  const activeMode = conversation?.mode ?? mode;
  const action = MODES.find((m) => m.id === activeMode)?.action ?? "Send";
  const marketName = markets.find((m) => m.id === (conversation?.market_id ?? marketId))?.name;

  return (
    <div className={styles.chat}>
      {started ? (
        <p className={styles.context}>
          {MODES.find((m) => m.id === activeMode)?.name} on {marketName ?? conversation.market_id},{" "}
          {conversation.timeframe} bars
        </p>
      ) : null}

      {messages.length > 0 ? (
        <ol className={styles.thread} aria-label="Conversation">
          {messages.map((message, index) =>
            message.role === "user" ? (
              <li key={message.id} className={styles.user}>
                {message.text ? <p>{message.text}</p> : null}
                {message.errorText ? (
                  <pre className={styles.pasted}>{message.errorText}</pre>
                ) : null}
                {message.code ? (
                  <details className={styles.pastedCode}>
                    <summary>Your code ({message.code.split("\n").length} lines)</summary>
                    <pre>{message.code}</pre>
                  </details>
                ) : null}
              </li>
            ) : (
              <li key={message.id} className={styles.assistant}>
                <AssistantMessage
                  message={message}
                  onApplyFixes={applyFixes}
                  busy={busy}
                  reviewedCode={codeBefore(messages, index)}
                />
              </li>
            ),
          )}
        </ol>
      ) : null}

      {busy ? (
        <section className={styles.progress} aria-live="polite" aria-label="Progress">
          {stages.length === 0 ? <p>Starting…</p> : null}
          <ol>
            {stages.map((stage, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: the list only grows, and a stage can repeat
              <li key={`${stage}-${index}`} data-current={index === stages.length - 1 || undefined}>
                {stageName(stage)}
              </li>
            ))}
          </ol>
          <button type="button" className={styles.secondary} onClick={() => abort.current?.abort()}>
            Stop
          </button>
        </section>
      ) : null}

      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}

      <form className={styles.composer} data-first={!started || undefined} onSubmit={submit}>
        {!started ? <h1 className={styles.title}>What do you need?</h1> : null}
        {!started ? (
          <div className={styles.setup}>
            <fieldset className={styles.modes}>
              <legend className="visually-hidden">What do you want to do?</legend>
              {MODES.map((m) => (
                <label key={m.id} data-checked={mode === m.id || undefined}>
                  <input
                    type="radio"
                    name="mode"
                    value={m.id}
                    checked={mode === m.id}
                    onChange={() => setMode(m.id)}
                  />
                  {m.name}
                </label>
              ))}
            </fieldset>
            <label>
              Market
              <select
                value={marketId}
                onChange={(e) => setMarketId(e.target.value)}
                disabled={markets.length === 0}
              >
                {markets.length === 0 ? <option value={marketId}>Loading…</option> : null}
                {markets.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Timeframe
              <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
                {TIMEFRAMES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
          </div>
        ) : null}

        {activeMode !== "write" ? (
          <label className={styles.field}>
            Your AFL code
            <textarea
              value={code}
              onChange={(e) => setCode(e.target.value)}
              rows={10}
              spellCheck={false}
              className={styles.codeInput}
              required
            />
          </label>
        ) : null}
        {activeMode === "fix" ? (
          <label className={styles.field}>
            The error AmiBroker showed
            <textarea
              value={errorText}
              onChange={(e) => setErrorText(e.target.value)}
              rows={3}
              spellCheck={false}
              className={styles.codeInput}
              required
            />
          </label>
        ) : null}
        <label className={styles.field}>
          {activeMode === "write"
            ? awaitingReply
              ? "Your answer"
              : started
                ? "What should change?"
                : "Describe your strategy"
            : "Anything else we should know (optional)"}
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={activeMode === "write" ? 4 : 2}
            required={activeMode === "write"}
            maxLength={4000}
            placeholder={
              activeMode === "write" && !started
                ? "For example: buy when the 9 EMA crosses above the 21 EMA, only between 9:30 and 2:30, close everything by 3:15."
                : undefined
            }
          />
        </label>
        <div className={styles.submitRow}>
          <button type="submit" className={styles.primary} disabled={busy || !ready}>
            {awaitingReply ? "Send answer" : action}
          </button>
          <span className={styles.small}>
            Writes code only. Not trading advice: backtest before you trade.
          </span>
        </div>
      </form>
    </div>
  );
}

/** The code of the latest user message before this point, for showing a review against it. */
function codeBefore(messages: Message[], index: number): string | null {
  for (let i = index - 1; i >= 0; i--) {
    const earlier = messages[i];
    if (earlier?.role === "user" && earlier.code) return earlier.code;
  }
  return null;
}

function AssistantMessage({
  message,
  onApplyFixes,
  busy,
  reviewedCode,
}: {
  message: Extract<Message, { role: "assistant" }>;
  onApplyFixes: (id: string) => void;
  busy: boolean;
  reviewedCode: string | null;
}) {
  const { answer } = message;
  if (answer.status === "clarify") {
    return (
      <div className={styles.questions}>
        <p>Before I write the code, I need to know:</p>
        <ul>
          {(message.questions ?? []).map((q) => (
            <li key={q}>{q}</li>
          ))}
        </ul>
      </div>
    );
  }
  if (answer.status === "error" || answer.status === "cancelled") {
    return <p className={styles.error}>{message.message || "There is no answer to show."}</p>;
  }
  const canFix =
    answer.kind === "review" && answer.findings.length > 0 && !message.id.startsWith("local-");
  return (
    <AnswerView
      answer={answer}
      reviewedCode={answer.kind === "review" ? reviewedCode : null}
      actions={
        message.id.startsWith("local-") ? null : (
          <>
            {canFix ? (
              <button
                type="button"
                className={styles.primary}
                disabled={busy}
                onClick={() => onApplyFixes(message.id)}
              >
                Apply all fixes
              </button>
            ) : null}
            <Feedback messageId={message.id} />
          </>
        )
      }
    />
  );
}
