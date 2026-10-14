// @vitest-environment node
// The BFF runs on the server, so its tests run in Node, not in a browser-like DOM.
import { SignJWT } from "jose";
import { describe, expect, it, vi } from "vitest";
import { serverConfig } from "./config";
import {
  clearedCookie,
  cookieValue,
  forward,
  forwardLogin,
  sameOrigin,
  sessionCookie,
} from "./forward";
import { readSession } from "./session";

const CONFIG = { apiUrl: "http://api.test", jwtSecret: "s".repeat(40), bffKey: "k".repeat(40) };
const SITE = "https://afl.example";
const USER = "4f1c2b3a-0000-4000-8000-000000000001";

async function token(
  changes: { secret?: string; alg?: string; exp?: number; sub?: string | null } = {},
) {
  const jwt = new SignJWT(changes.sub === null ? {} : { sub: changes.sub ?? USER })
    .setProtectedHeader({ alg: changes.alg ?? "HS256" })
    .setIssuedAt()
    .setExpirationTime(changes.exp ?? Math.floor(Date.now() / 1000) + 3600);
  return jwt.sign(new TextEncoder().encode(changes.secret ?? CONFIG.jwtSecret));
}

function request(path: string, init: RequestInit & { cookie?: string } = {}) {
  const headers = new Headers(init.headers);
  if (init.cookie) headers.set("cookie", init.cookie);
  if (init.method && init.method !== "GET" && !headers.has("origin")) headers.set("origin", SITE);
  return new Request(`${SITE}${path}`, { ...init, headers });
}

function fakeApi(reply: Response = Response.json({ ok: true })) {
  return vi.fn<typeof fetch>(async () => reply);
}

describe("session", () => {
  it("accepts a valid token and names the user", async () => {
    const valid = await token();
    expect(await readSession(valid, CONFIG.jwtSecret)).toEqual({ userId: USER, token: valid });
  });

  it.each([
    ["missing", undefined],
    ["garbage", "not.a.token"],
  ])("refuses a %s token", async (_, value) => {
    expect(await readSession(value, CONFIG.jwtSecret)).toBeNull();
  });

  it("refuses an expired token", async () => {
    const expired = await token({ exp: Math.floor(Date.now() / 1000) - 10 });
    expect(await readSession(expired, CONFIG.jwtSecret)).toBeNull();
  });

  it("refuses a token signed with another secret", async () => {
    expect(await readSession(await token({ secret: "t".repeat(40) }), CONFIG.jwtSecret)).toBeNull();
  });

  it("refuses another algorithm", async () => {
    expect(await readSession(await token({ alg: "HS512" }), CONFIG.jwtSecret)).toBeNull();
  });

  it("refuses a token that names no user", async () => {
    expect(await readSession(await token({ sub: null }), CONFIG.jwtSecret)).toBeNull();
  });
});

describe("forward", () => {
  it("sends the token and the shared key and passes the reply back", async () => {
    const api = fakeApi(Response.json({ used: 1 }, { status: 200 }));
    const valid = await token();
    const reply = await forward(
      request("/api/usage", {
        cookie: `session=${valid}`,
        headers: { "x-forwarded-for": "203.0.113.5, 10.0.0.1" },
      }),
      "/v1/me/usage",
      CONFIG,
      { auth: true, fetcher: api },
    );
    expect(reply.status).toBe(200);
    expect(await reply.json()).toEqual({ used: 1 });
    const [url, init] = api.mock.calls[0] ?? [];
    expect(url).toBe("http://api.test/v1/me/usage");
    const sent = new Headers(init?.headers);
    expect(sent.get("Authorization")).toBe(`Bearer ${valid}`);
    expect(sent.get("X-Internal-Key")).toBe(CONFIG.bffKey);
    expect(sent.get("X-Client-IP")).toBe("203.0.113.5");
    expect(sent.get("cookie")).toBeNull();
  });

  it("refuses a request without a valid session and clears the cookie, calling nothing", async () => {
    const api = fakeApi();
    const reply = await forward(
      request("/api/usage", { cookie: "session=garbage" }),
      "/v1/me/usage",
      CONFIG,
      {
        auth: true,
        fetcher: api,
      },
    );
    expect(reply.status).toBe(401);
    expect(reply.headers.get("set-cookie")).toContain("Max-Age=0");
    expect(api).not.toHaveBeenCalled();
  });

  it.each([
    ["no origin", undefined],
    ["another site", "https://evil.example"],
    ["another scheme", "http://afl.example"],
  ])("refuses a change from %s", async (_, origin) => {
    const api = fakeApi();
    const headers: Record<string, string> = origin ? { origin } : {};
    const plain = new Request(`${SITE}/api/conversations`, { method: "POST", headers, body: "{}" });
    const reply = await forward(plain, "/v1/conversations", CONFIG, { auth: true, fetcher: api });
    expect(reply.status).toBe(403);
    expect(api).not.toHaveBeenCalled();
  });

  it("forwards the body of a change from this site", async () => {
    const api = fakeApi(Response.json({ id: "c1" }, { status: 201 }));
    const reply = await forward(
      request("/api/conversations", {
        method: "POST",
        body: '{"mode":"write"}',
        cookie: `session=${await token()}`,
      }),
      "/v1/conversations",
      CONFIG,
      { auth: true, fetcher: api },
    );
    expect(reply.status).toBe(201);
    expect(api.mock.calls[0]?.[1]?.body).toBe('{"mode":"write"}');
  });

  it("passes an event stream through as it arrives", async () => {
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode('event: status\ndata: {"stage":"writing"}\n\n'),
        );
        controller.close();
      },
    });
    const api = fakeApi(new Response(body, { headers: { "content-type": "text/event-stream" } }));
    const reply = await forward(
      request("/api/conversations/x/messages", {
        method: "POST",
        body: "{}",
        cookie: `session=${await token()}`,
      }),
      "/v1/conversations/x/messages",
      CONFIG,
      { auth: true, stream: true, fetcher: api },
    );
    expect(reply.headers.get("content-type")).toBe("text/event-stream");
    expect(await reply.text()).toBe('event: status\ndata: {"stage":"writing"}\n\n');
  });

  it("passes an API error through, and a refused session clears the cookie", async () => {
    const api = fakeApi(
      Response.json({ error: { code: "unauthorized", message: "x" } }, { status: 401 }),
    );
    const reply = await forward(
      request("/api/usage", { cookie: `session=${await token()}` }),
      "/v1/me/usage",
      CONFIG,
      {
        auth: true,
        fetcher: api,
      },
    );
    expect(reply.status).toBe(401);
    expect(reply.headers.get("set-cookie")).toContain("Max-Age=0");
  });

  it("says plainly when the API cannot be reached", async () => {
    const api = vi.fn<typeof fetch>(async () => {
      throw new TypeError("fetch failed");
    });
    const reply = await forward(
      request("/api/usage", { cookie: `session=${await token()}` }),
      "/v1/me/usage",
      CONFIG,
      {
        auth: true,
        fetcher: api,
      },
    );
    expect(reply.status).toBe(502);
    expect((await reply.json()).error.code).toBe("unreachable");
  });
});

describe("login", () => {
  it("keeps the token in an httpOnly cookie and never sends it to the browser", async () => {
    const api = fakeApi(Response.json({ token: "the.session.token" }, { status: 200 }));
    const reply = await forwardLogin(
      request("/api/auth/login", { method: "POST", body: '{"email":"a@b.in","password":"x"}' }),
      "/v1/auth/login",
      CONFIG,
      api,
    );
    expect(reply.status).toBe(200);
    const text = await reply.text();
    expect(text).not.toContain("the.session.token");
    const cookie = reply.headers.get("set-cookie") ?? "";
    expect(cookie).toContain("session=the.session.token");
    expect(cookie).toContain("HttpOnly");
    expect(cookie).toContain("Secure");
    expect(cookie).toContain("SameSite=Lax");
    expect(new Headers(api.mock.calls[0]?.[1]?.headers).get("Authorization")).toBeNull();
  });

  it("passes a failed login through without a cookie", async () => {
    const api = fakeApi(
      Response.json({ error: { code: "wrong_login", message: "x" } }, { status: 401 }),
    );
    const reply = await forwardLogin(
      request("/api/auth/login", { method: "POST", body: "{}" }),
      "/v1/auth/login",
      CONFIG,
      api,
    );
    expect(reply.status).toBe(401);
    expect(reply.headers.get("set-cookie")).toBeNull();
  });
});

describe("cookies and settings", () => {
  it("reads a cookie among others", () => {
    const req = new Request(SITE, { headers: { cookie: "a=1; session=tok%3Den; b=2" } });
    expect(cookieValue(req, "session")).toBe("tok=en");
    expect(cookieValue(req, "missing")).toBeUndefined();
  });

  it("drops Secure only for plain http on this machine", () => {
    expect(sessionCookie("t", false)).not.toContain("Secure");
    expect(clearedCookie(true)).toContain("Secure");
  });

  it("allows reads from anywhere and changes only from this site", () => {
    expect(sameOrigin(new Request(SITE, { method: "GET" }))).toBe(true);
    expect(sameOrigin(new Request(SITE, { method: "POST", headers: { origin: SITE } }))).toBe(true);
    expect(sameOrigin(new Request(SITE, { method: "DELETE" }))).toBe(false);
  });

  it("refuses short secrets and a missing API address", () => {
    expect(() =>
      serverConfig({ API_URL: "x", JWT_SECRET: "short", BFF_SHARED_SECRET: "k".repeat(40) }),
    ).toThrow("JWT_SECRET");
    expect(() =>
      serverConfig({ JWT_SECRET: "s".repeat(40), BFF_SHARED_SECRET: "k".repeat(40) }),
    ).toThrow("API_URL");
    expect(
      serverConfig({
        API_URL: "http://api/",
        JWT_SECRET: "s".repeat(40),
        BFF_SHARED_SECRET: "k".repeat(40),
      }).apiUrl,
    ).toBe("http://api");
  });
});
