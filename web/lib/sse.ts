/** Reads Server-Sent Events from a stream that arrives in arbitrary chunks. */

export type StreamEvent = { event: string; data: unknown };

export class SseParser {
  private buffer = "";

  constructor(private readonly onEvent: (event: StreamEvent) => void) {}

  feed(chunk: string): void {
    this.buffer += chunk.replace(/\r\n/g, "\n");
    let end = this.buffer.indexOf("\n\n");
    while (end !== -1) {
      this.dispatch(this.buffer.slice(0, end));
      this.buffer = this.buffer.slice(end + 2);
      end = this.buffer.indexOf("\n\n");
    }
  }

  private dispatch(block: string): void {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith(":")) continue; // a keep-alive comment
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (data.length === 0) return;
    const text = data.join("\n");
    let parsed: unknown = text;
    try {
      parsed = JSON.parse(text);
    } catch {
      // Not JSON: pass the text on as it is.
    }
    this.onEvent({ event, data: parsed });
  }
}
