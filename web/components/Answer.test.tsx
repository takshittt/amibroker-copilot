import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CHECKED, NOT_FULLY_CHECKED, REVIEW } from "@/lib/fixtures";
import type { CodeAnswer } from "@/lib/types";
import { AnswerView } from "./Answer";

describe("AnswerView", () => {
  it("shows checked code as checked, with every check listed", () => {
    render(<AnswerView answer={CHECKED} />);
    expect(screen.getByText("Checked")).toBeInTheDocument();
    const checks = screen.getByRole("region", { name: "Checks" });
    expect(within(checks).getAllByRole("listitem")).toHaveLength(12);
    expect(screen.getByRole("figure", { name: "Code" })).toHaveTextContent(
      "Buy = CrossUp AND CanEnter;",
    );
    expect(screen.getByRole("link", { name: "EMA" })).toHaveAttribute(
      "href",
      "https://www.amibroker.com/guide/afl/ema.html",
    );
  });

  it("never shows code that failed its checks as checked", () => {
    render(<AnswerView answer={NOT_FULLY_CHECKED} />);
    expect(screen.queryByText("Checked")).not.toBeInTheDocument();
    expect(screen.getByText("Not fully checked")).toBeInTheDocument();
    const failures = screen.getByRole("list", { name: "What still fails" });
    expect(failures).toHaveTextContent("ZLEMA is not an AFL function.");
    expect(screen.getByText(/Checker found a problem on line 17/)).toBeInTheDocument();
  });

  it("says plainly when the checker could not run", () => {
    const crashed: CodeAnswer = { ...CHECKED, status: "not_checked", checks: [], problems: [] };
    render(<AnswerView answer={crashed} />);
    expect(screen.getByText("Not checked")).toBeInTheDocument();
    expect(screen.queryByText("Checked")).not.toBeInTheDocument();
    expect(screen.getByText(/nothing about it is verified/)).toBeInTheDocument();
  });

  it("keeps verified and AI-suggested findings in separate, labelled groups", () => {
    render(<AnswerView answer={REVIEW} reviewedCode={"a = 1;\n".repeat(12)} />);
    const verified = screen.getByRole("region", { name: "Verified by the checker" });
    const ai = screen.getByRole("region", { name: "Suggested by the AI review" });
    expect(verified).toHaveTextContent("reads future bars");
    expect(verified).not.toHaveTextContent("Short opens");
    expect(ai).toHaveTextContent("Short opens on the same cross");
    expect(ai).toHaveTextContent("Nothing here is verified.");
    expect(screen.getByText(/AI suggestion, not verified on line 12/)).toBeInTheDocument();
  });

  it("an empty review says it proves nothing", () => {
    render(<AnswerView answer={{ ...REVIEW, findings: [], checker_status: "passed" }} />);
    expect(screen.getByText("Nothing found")).toBeInTheDocument();
    expect(screen.getByText(/does not prove the code is correct/)).toBeInTheDocument();
  });
});
