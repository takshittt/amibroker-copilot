/** The browser's calls. They go only to this site's own /api routes, never to the API itself. */

import { SseParser } from "./sse";
import type { Answer, CodeAnswer, ReviewAnswer } from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

async function errorFrom(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as { error?: { code?: string; message?: string } };
    return new ApiError(
      response.status,
      body.error?.code ?? "error",
      body.error?.message ?? "Something went wrong.",
    );
  } catch {
    return new ApiError(
      response.status,
      "error",
      "Something went wrong on our side. Please try again.",
    );
  }
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw await errorFrom(response);
  return (await response.json()) as T;
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw await errorFrom(response);
  return (response.status === 204 ? null : await response.json()) as T;
}

export type Progress = (stage: string) => void;

/** Sends a request that answers with an event stream; returns the final event. */
export async function postStream(
  path: string,
  body: unknown,
  onProgress: Progress,
  signal?: AbortSignal,
): Promise<{ event: string; data: Record<string, unknown> }> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) throw await errorFrom(response);
  let last: { event: string; data: Record<string, unknown> } | null = null;
  const parser = new SseParser(({ event, data }) => {
    if (event === "status") onProgress(String((data as { stage?: string }).stage ?? ""));
    else last = { event, data: data as Record<string, unknown> };
  });
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    parser.feed(value);
  }
  if (!last)
    throw new ApiError(
      502,
      "no_answer",
      "The answer stopped before it was complete. Please try again.",
    );
  return last;
}

/** Turns what the API returned, live or from history, into an answer to show. */
export function toAnswer(mode: string, data: Record<string, unknown>): Answer {
  if (mode === "review" && Array.isArray(data.findings)) {
    return { kind: "review", ...data } as unknown as ReviewAnswer;
  }
  return { kind: mode === "write" ? "write" : "fix", ...data } as unknown as CodeAnswer;
}

const STAGES: Record<string, string> = {
  understanding: "Reading your request",
  searching: "Finding the functions and notes it needs",
  writing: "Writing the code",
  checking: "Checking it",
  reviewing: "Reviewing the code",
  fixing: "Correcting the code",
};

export function stageName(stage: string): string {
  const retry = /^(?:fixing attempt) (\d+)$/.exec(stage);
  if (retry) return `Fixing what the checker found, attempt ${retry[1]}`;
  return STAGES[stage] ?? stage;
}
