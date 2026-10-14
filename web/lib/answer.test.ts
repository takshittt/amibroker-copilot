import { describe, expect, it } from "vitest";
import { codeHeadline, headline, marks, reviewHeadline } from "./answer";
import type { CodeAnswer, ReviewAnswer } from "./types";

const base: CodeAnswer = {
  kind: "write",
  status: "checked",
  code: "Buy = 1;\nSell = 0;\n",
  checks: [
    { name: "syntax", outcome: "passed" },
    { name: "unknown_function", outcome: "passed" },
  ],
  problems: [],
  doc_links: [],
  notes: [],
  message: "",
};

describe("the headline never calls unchecked code checked", () => {
  it("checked code says checked", () => {
    expect(codeHeadline(base)).toMatchObject({ tone: "checked", title: "Checked" });
  });

  it.each(["not_fully_checked", "not_checked"] as const)("%s never does", (status) => {
    const answer = {
      ...base,
      status,
      problems: [
        {
          rule: "unknown_function",
          source: "checker",
          severity: "critical",
          line: 1,
          message: "x",
          fix: "",
        },
      ],
    } satisfies CodeAnswer;
    const shown = headline(answer);
    expect(shown.tone).not.toBe("checked");
    expect(shown.title.toLowerCase()).toContain("not");
  });

  it("not fully checked counts the problems", () => {
    const answer: CodeAnswer = {
      ...base,
      status: "not_fully_checked",
      problems: [
        {
          rule: "eod_exit",
          source: "checker",
          severity: "warning",
          line: 3,
          message: "a",
          fix: "",
        },
        {
          rule: "requirements_covered",
          source: "coverage",
          severity: "critical",
          line: null,
          message: "b",
          fix: "",
        },
      ],
    };
    expect(codeHeadline(answer).detail).toContain("2 problems");
  });
});

const review: ReviewAnswer = {
  kind: "review",
  status: "reviewed",
  findings: [
    {
      label: "Verified",
      severity: "critical",
      line: 4,
      message: "Reads a future bar.",
      fix: "",
      rule: "lookahead_ref",
    },
    {
      label: "AI-suggested",
      severity: "warning",
      line: 5,
      message: "Cross looks swapped.",
      fix: "",
      rule: "ai_review",
    },
    {
      label: "AI-suggested",
      severity: "tip",
      line: null,
      message: "About the whole code.",
      fix: "",
      rule: "ai_review",
    },
  ],
  checks: [],
  checker_status: "failed",
  ai_review: "done",
  summary: "",
  notes: [],
  message: "",
};

describe("review", () => {
  it("counts verified and AI findings apart", () => {
    expect(reviewHeadline(review).detail).toBe(
      "1 verified by the checker, 2 suggested by the AI review.",
    );
  });

  it("an empty review says it proves nothing", () => {
    expect(reviewHeadline({ ...review, findings: [] }).detail).toContain("does not prove");
  });

  it("a checker crash is never read as a clean result", () => {
    const shown = reviewHeadline({ ...review, findings: [], checker_status: "checker_error" });
    expect(shown.tone).toBe("unverified");
    expect(shown.detail).toContain("does not mean the code is correct");
  });

  it("marks keep AI findings apart from verified ones and skip findings with no line", () => {
    expect(marks(review)).toEqual([
      { line: 4, kind: "fail", text: "Reads a future bar." },
      { line: 5, kind: "ai", text: "Cross looks swapped." },
    ]);
  });
});

describe("marks on written code", () => {
  it("checked code has no marks", () => {
    expect(marks(base)).toEqual([]);
  });

  it("problems with a line become marks", () => {
    const answer: CodeAnswer = {
      ...base,
      status: "not_fully_checked",
      problems: [
        {
          rule: "hardcoded_times",
          source: "checker",
          severity: "tip",
          line: 2,
          message: "Time in logic.",
          fix: "",
        },
        {
          rule: "requirements_covered",
          source: "coverage",
          severity: "critical",
          line: null,
          message: "x",
          fix: "",
        },
      ],
    };
    expect(marks(answer)).toEqual([{ line: 2, kind: "tip", text: "Time in logic." }]);
  });
});
