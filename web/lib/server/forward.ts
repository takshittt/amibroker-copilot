/**
 * The BFF's only job: check the session, forward the request to the API
 * with the token and the shared key, and pass the reply back unchanged.
 * There is no business logic here.
 */

import { SESSION_COOKIE, SESSION_DAYS, type ServerConfig } from "./config";
import { readSession } from "./session";

const KEY_HEADER = "X-Internal-Key";
const CLIENT_IP_HEADER = "X-Client-IP";
const SAFE_METHODS = new Set(["GET", "HEAD"]);

export function cookieValue(request: Request, name: string): string | undefined {
  const header = request.headers.get("cookie") ?? "";
  for (const part of header.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return undefined;
}

export function sessionCookie(token: string, secure: boolean): string {
  const maxAge = SESSION_DAYS * 24 * 60 * 60;
  return [
    `${SESSION_COOKIE}=${encodeURIComponent(token)}`,
    "Path=/",
    "HttpOnly",
    "SameSite=Lax",
    `Max-Age=${maxAge}`,
    ...(secure ? ["Secure"] : []),
  ].join("; ");
}

export function clearedCookie(secure: boolean): string {
  return [
    `${SESSION_COOKIE}=`,
    "Path=/",
    "HttpOnly",
    "SameSite=Lax",
    "Max-Age=0",
    ...(secure ? ["Secure"] : []),
  ].join("; ");
}

/** Secure cookies everywhere except plain http on this machine during development. */
export function isSecure(request: Request): boolean {
  const url = new URL(request.url);
  return !(
    url.protocol === "http:" &&
    (url.hostname === "localhost" || url.hostname === "127.0.0.1")
  );
}

/** A request that changes something must come from this site's own pages. */
export function sameOrigin(request: Request): boolean {
  if (SAFE_METHODS.has(request.method)) return true;
  const origin = request.headers.get("origin");
  if (!origin) return false;
  return origin === new URL(request.url).origin;
}

export function clientIp(request: Request): string {
  const forwarded = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  return forwarded || request.headers.get("x-real-ip") || "";
}

export function jsonError(
  status: number,
  code: string,
  message: string,
  extraHeaders: HeadersInit = {},
): Response {
  return new Response(JSON.stringify({ error: { code, message } }), {
    status,
    headers: { "Content-Type": "application/json", ...extraHeaders },
  });
}

type ForwardOptions = {
  /** Whether a signed-in session is required. */
  auth: boolean;
  /** Whether the reply is an event stream to pass through as it arrives. */
  stream?: boolean;
  fetcher?: typeof fetch;
};

/** Forwards `request` to `path` on the API. */
export async function forward(
  request: Request,
  path: string,
  config: ServerConfig,
  options: ForwardOptions,
): Promise<Response> {
  if (!sameOrigin(request)) {
    return jsonError(403, "forbidden", "This request did not come from the AFL Copilot website.");
  }
  const headers = new Headers({ [KEY_HEADER]: config.bffKey });
  const ip = clientIp(request);
  if (ip) headers.set(CLIENT_IP_HEADER, ip);
  if (options.auth) {
    const session = await readSession(cookieValue(request, SESSION_COOKIE), config.jwtSecret);
    if (!session) {
      return jsonError(401, "unauthorized", "Please sign in again.", {
        "Set-Cookie": clearedCookie(isSecure(request)),
      });
    }
    headers.set("Authorization", `Bearer ${session.token}`);
  }
  const hasBody = !SAFE_METHODS.has(request.method);
  if (hasBody) headers.set("Content-Type", "application/json");

  const fetcher = options.fetcher ?? fetch;
  let upstream: Response;
  try {
    upstream = await fetcher(`${config.apiUrl}${path}`, {
      method: request.method,
      headers,
      body: hasBody ? await request.text() : undefined,
      // If the browser goes away, the API sees the disconnect and stops the run.
      signal: request.signal,
      cache: "no-store",
    });
  } catch {
    return jsonError(
      502,
      "unreachable",
      "The service is not reachable right now. Please try again.",
    );
  }

  const isStream =
    options.stream &&
    upstream.ok &&
    (upstream.headers.get("content-type") ?? "").startsWith("text/event-stream");
  if (isStream) {
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
      },
    });
  }
  const outHeaders: Record<string, string> = {
    "Content-Type": upstream.headers.get("content-type") ?? "application/json",
  };
  if (upstream.status === 401 && options.auth) {
    // The API no longer accepts this session (the user was removed, say).
    outHeaders["Set-Cookie"] = clearedCookie(isSecure(request));
  }
  return new Response(upstream.status === 204 ? null : await upstream.text(), {
    status: upstream.status,
    headers: outHeaders,
  });
}

/**
 * Sign-up and login: forwards, and on success puts the token in the
 * session cookie. The token itself is never sent to the browser.
 */
export async function forwardLogin(
  request: Request,
  path: string,
  config: ServerConfig,
  fetcher?: typeof fetch,
): Promise<Response> {
  const reply = await forward(request, path, config, { auth: false, fetcher });
  if (!reply.ok) return reply;
  const body = (await reply.json()) as { token?: string };
  if (!body.token)
    return jsonError(502, "bad_reply", "Something went wrong on our side. Please try again.");
  return new Response(JSON.stringify({ ok: true }), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      "Set-Cookie": sessionCookie(body.token, isSecure(request)),
    },
  });
}
