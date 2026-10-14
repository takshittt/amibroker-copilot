import { describe, expect, it } from "vitest";
import { stageName, toAnswer } from "./client";

describe("toAnswer", () => {
  it("a review with findings is a review", () => {
    expect(toAnswer("review", { findings: [], status: "reviewed" }).kind).toBe("review");
  });

  it("corrected code in a review conversation is a code answer", () => {
    expect(toAnswer("review", { code: "x", status: "checked" }).kind).toBe("fix");
  });

  it("write and fix keep their kind", () => {
    expect(toAnswer("write", { code: "x" }).kind).toBe("write");
    expect(toAnswer("fix", { code: "x" }).kind).toBe("fix");
  });
});

describe("stageName", () => {
  it("names each step in plain words", () => {
    expect(stageName("understanding")).toBe("Reading your request");
    expect(stageName("fixing attempt 2")).toBe("Fixing what the checker found, attempt 2");
    expect(stageName("something new")).toBe("something new");
  });
});
