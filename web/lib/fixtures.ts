/**
 * Example answers, for the landing page, the design preview and the tests.
 * The code is the intraday example from kb/examples, which passes the
 * real checker with nothing reported.
 */

import type { CodeAnswer, ReviewAnswer } from "./types";

export const EXAMPLE_REQUEST =
  "Nifty futures, 5-minute bars. Long when the 9 EMA crosses above the 21 EMA, short when it crosses below. No new trades after 2:30, everything closed by 3:15.";

export const EXAMPLE_CODE = `// Session times: change these for another market or data feed.
FirstEntryTime = ParamTime("First entry", "09:30");
LastEntryTime = ParamTime("Last entry", "14:30");
ExitTime = ParamTime("Exit time", "15:15");

FastLen = Param("Fast EMA", 9, 2, 50, 1);
SlowLen = Param("Slow EMA", 21, 5, 200, 1);

SetTradeDelays(0, 0, 0, 0);
SetPositionSize(1, spsShares);

tn = TimeNum();
CanEnter = tn >= FirstEntryTime AND tn <= LastEntryTime;
DayEnd = tn >= ExitTime;

Fast = EMA(Close, FastLen);
Slow = EMA(Close, SlowLen);
CrossUp = Cross(Fast, Slow);
CrossDown = Cross(Slow, Fast);

Buy = CrossUp AND CanEnter;
Sell = CrossDown OR DayEnd;
Short = CrossDown AND CanEnter;
Cover = CrossUp OR DayEnd;

BuyPrice = SellPrice = ShortPrice = CoverPrice = Close;
`;

const ALL_CHECKS = [
  "syntax",
  "unknown_function",
  "arg_count",
  "if_on_array",
  "lookahead_ref",
  "eod_exit",
  "intrabar_stop_price",
  "trade_delays",
  "exrem",
  "hardcoded_times",
  "requirements_covered",
  "v1_scope",
];

export const CHECKED: CodeAnswer = {
  kind: "write",
  status: "checked",
  code: EXAMPLE_CODE,
  explanation: [
    {
      start_line: 1,
      end_line: 4,
      text: "All three session times are parameters you can change for another market.",
    },
    { start_line: 6, end_line: 7, text: "The two EMA lengths, also parameters." },
    {
      start_line: 9,
      end_line: 10,
      text: "Trades fill on the signal bar's close, one contract at a time.",
    },
    {
      start_line: 12,
      end_line: 14,
      text: "Entries only inside the window; DayEnd turns true at the exit time.",
    },
    {
      start_line: 16,
      end_line: 19,
      text: "The crossovers, worked out once and used for both sides.",
    },
    {
      start_line: 21,
      end_line: 24,
      text: "Long and short entries and exits; both sides close at the exit time.",
    },
  ],
  checks: ALL_CHECKS.map((name) => ({ name, outcome: "passed" as const })),
  problems: [],
  doc_links: [
    "ParamTime",
    "Param",
    "SetTradeDelays",
    "SetPositionSize",
    "TimeNum",
    "EMA",
    "Cross",
  ].map((name) => ({
    name,
    url: `https://www.amibroker.com/guide/afl/${name.toLowerCase()}.html`,
  })),
  notes: [
    "This code uses the time of each bar. If your data feed is in a different time zone from the exchange, the times will be off. Check the first and last bar of a session on an intraday chart.",
  ],
  message: "",
};

export const NOT_FULLY_CHECKED: CodeAnswer = {
  ...CHECKED,
  status: "not_fully_checked",
  code: EXAMPLE_CODE.replace("Sell = CrossDown OR DayEnd;", "Sell = CrossDown;").replace(
    "Slow = EMA(Close, SlowLen);",
    "Slow = ZLEMA(Close, SlowLen);",
  ),
  checks: ALL_CHECKS.map((name) => ({
    name,
    outcome:
      name === "unknown_function" || name === "eod_exit"
        ? ("failed" as const)
        : ("passed" as const),
  })),
  problems: [
    {
      rule: "unknown_function",
      source: "checker",
      severity: "critical",
      line: 17,
      message: "ZLEMA is not an AFL function.",
      fix: "Use a function from the AFL function list.",
    },
    {
      rule: "eod_exit",
      source: "checker",
      severity: "warning",
      line: 22,
      message: "Sell never depends on the time of day, so long positions can be carried overnight.",
      fix: "Add 'OR DayEnd' to Sell.",
    },
  ],
};

export const REVIEW: ReviewAnswer = {
  kind: "review",
  status: "reviewed",
  findings: [
    {
      label: "Verified",
      severity: "critical",
      line: 9,
      message: "Ref with a positive period (1) reads future bars, and Buy depends on it.",
      fix: "Use a negative period, for example Ref(x, -1).",
      rule: "lookahead_ref",
    },
    {
      label: "AI-suggested",
      severity: "warning",
      line: 12,
      message: "Short opens on the same cross as Buy, so both sides enter together.",
      fix: "Use Cross(Slow, Fast) for Short.",
      rule: "ai_review",
    },
  ],
  checks: ALL_CHECKS.slice(0, 10).map((name) => ({
    name,
    outcome: name === "lookahead_ref" ? ("failed" as const) : ("passed" as const),
  })),
  checker_status: "failed",
  ai_review: "done",
  summary: "One look-ahead the checker caught, and one logic slip it cannot see.",
  notes: [],
  message: "",
};
