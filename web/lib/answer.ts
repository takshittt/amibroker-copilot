/**
 * How an answer is presented. Kept apart from the components so the rule
 * that matters most can be tested on its own: code is shown as checked
 * only when the checker passed it, and never otherwise.
 */

import type { Answer, CodeAnswer, Finding, ReviewAnswer } from "./types";

export type Tone = "checked" | "failed" | "unverified" | "neutral";

export type Headline = { tone: Tone; title: string; detail: string };

const CHECK_NAMES: Record<string, string> = {
  syntax: "Brackets, semicolons and comparisons",
  unknown_function: "Every function exists in AmiBroker",
  arg_count: "Each function gets the right number of inputs",
  if_on_array: "No if statement on a whole array",
  lookahead_ref: "No signal reads a future bar",
  eod_exit: "Intraday trades close before the session ends",
  intrabar_stop_price: "Stops hit inside a bar fill at the stop",
  trade_delays: "Trade delays are set and match the prices",
  exrem: "Plotted signals are cleaned with ExRem",
  hardcoded_times: "Session times are parameters",
  requirements_covered: "Every part of your request is in the code",
  v1_scope: "Only features this tool supports",
};

export function checkName(rule: string): string {
  return CHECK_NAMES[rule] ?? rule;
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

export function codeHeadline(answer: CodeAnswer): Headline {
  const passed = answer.checks.filter((c) => c.outcome === "passed").length;
  switch (answer.status) {
    case "checked":
      return {
        tone: "checked",
        title: "Checked",
        detail: `Passed all ${plural(passed, "check", "checks")} below.`,
      };
    case "not_fully_checked":
      return {
        tone: "failed",
        title: "Not fully checked",
        detail: `${plural(answer.problems.length, "problem", "problems")} remained after the last attempt. Read them before you use this code.`,
      };
    case "not_checked":
      return {
        tone: "unverified",
        title: "Not checked",
        detail: "The checker could not run on this code, so nothing about it is verified.",
      };
    default:
      return { tone: "neutral", title: "", detail: answer.message };
  }
}

export function reviewHeadline(answer: ReviewAnswer): Headline {
  const verified = answer.findings.filter((f) => f.label === "Verified").length;
  const ai = answer.findings.length - verified;
  if (answer.checker_status === "checker_error") {
    return {
      tone: "unverified",
      title: "The checker could not run",
      detail: "There are no verified findings. That does not mean the code is correct.",
    };
  }
  if (answer.findings.length === 0) {
    return {
      tone: "neutral",
      title: "Nothing found",
      detail:
        "Neither the checker nor the AI review found a problem. That does not prove the code is correct.",
    };
  }
  return {
    tone: verified > 0 ? "failed" : "neutral",
    title: `${plural(answer.findings.length, "finding", "findings")}`,
    detail: `${verified} verified by the checker, ${ai} suggested by the AI review.`,
  };
}

export function headline(answer: Answer): Headline {
  return answer.kind === "review" ? reviewHeadline(answer) : codeHeadline(answer);
}

/** A mark printed in the listing's gutter, beside the line it is about. */
export type Mark = { line: number; kind: "fail" | "ai" | "tip"; text: string };

export function marks(answer: Answer): Mark[] {
  if (answer.kind === "review") {
    return answer.findings
      .filter((f): f is Finding & { line: number } => f.line !== null)
      .map((f) => ({
        line: f.line,
        kind: f.label === "AI-suggested" ? "ai" : f.severity === "tip" ? "tip" : "fail",
        text: f.message,
      }));
  }
  if (answer.status === "checked") return [];
  return answer.problems
    .filter((p) => p.line !== null)
    .map((p) => ({
      line: p.line as number,
      kind: p.severity === "tip" ? "tip" : "fail",
      text: p.message,
    }));
}

export function lines(code: string): string[] {
  return code.replace(/\n$/, "").split("\n");
}
