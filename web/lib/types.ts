/** The shapes the API sends back; see api/copilot/api/answers.py. */

export type Check = { name: string; outcome: "passed" | "failed" | "skipped" };

export type Problem = {
  rule: string;
  source: string;
  severity: "critical" | "warning" | "tip";
  line: number | null;
  message: string;
  fix: string;
};

export type Finding = {
  label: "Verified" | "AI-suggested";
  severity: "critical" | "warning" | "tip";
  line: number | null;
  message: string;
  fix: string;
  rule: string;
};

export type DocLink = { name: string; url: string };

export type CodeAnswer = {
  kind: "write" | "fix";
  message_id?: string;
  status: "checked" | "not_fully_checked" | "not_checked" | "clarify" | "error" | "cancelled";
  questions?: string[];
  code: string;
  explanation?: { start_line: number; end_line: number; text: string }[];
  changes?: { line: number; text: string }[];
  checks: Check[];
  problems: Problem[];
  doc_links: DocLink[];
  notes: string[];
  message: string;
};

export type ReviewAnswer = {
  kind: "review";
  message_id?: string;
  status: "reviewed" | "error" | "cancelled";
  findings: Finding[];
  checks: Check[];
  checker_status: "passed" | "failed" | "checker_error" | "";
  ai_review: "done" | "failed" | "";
  summary: string;
  notes: string[];
  message: string;
};

export type Answer = CodeAnswer | ReviewAnswer;
