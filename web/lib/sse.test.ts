import { describe, expect, it } from "vitest";
import { SseParser, type StreamEvent } from "./sse";

function parse(chunks: string[]): StreamEvent[] {
  const seen: StreamEvent[] = [];
  const parser = new SseParser((event) => seen.push(event));
  for (const chunk of chunks) parser.feed(chunk);
  return seen;
}

describe("SseParser", () => {
  it("reads whole events", () => {
    expect(
      parse(['event: status\ndata: {"stage":"writing"}\n\nevent: result\ndata: {"code":"x"}\n\n']),
    ).toEqual([
      { event: "status", data: { stage: "writing" } },
      { event: "result", data: { code: "x" } },
    ]);
  });

  it("joins an event split across chunks, even mid-line", () => {
    expect(parse(["event: sta", 'tus\ndata: {"sta', 'ge":"checking"}\n', "\n"])).toEqual([
      { event: "status", data: { stage: "checking" } },
    ]);
  });

  it("skips keep-alive comments", () => {
    expect(parse([": still working\n\n", 'event: result\ndata: {"a":1}\n\n'])).toEqual([
      { event: "result", data: { a: 1 } },
    ]);
  });

  it("handles Windows line endings and data that is not JSON", () => {
    expect(parse(["event: note\r\ndata: plain text\r\n\r\n"])).toEqual([
      { event: "note", data: "plain text" },
    ]);
  });

  it("holds back an incomplete event", () => {
    expect(parse(['event: result\ndata: {"a":1}\n'])).toEqual([]);
  });
});
