/** Server-only settings. None of these ever reach the browser. */

export const SESSION_COOKIE = "session";
export const SESSION_DAYS = 7;

export type ServerConfig = {
  apiUrl: string;
  jwtSecret: string;
  bffKey: string;
};

export function serverConfig(env: Record<string, string | undefined> = process.env): ServerConfig {
  const apiUrl = (env.API_URL ?? "").replace(/\/+$/, "");
  const jwtSecret = env.JWT_SECRET ?? "";
  const bffKey = env.BFF_SHARED_SECRET ?? "";
  if (!apiUrl) throw new Error("API_URL must be set");
  if (new TextEncoder().encode(jwtSecret).length < 32) {
    throw new Error("JWT_SECRET must be at least 32 bytes");
  }
  if (new TextEncoder().encode(bffKey).length < 32) {
    throw new Error("BFF_SHARED_SECRET must be at least 32 bytes");
  }
  return { apiUrl, jwtSecret, bffKey };
}

/** Where users write for a password reset; shown on the login page. */
export function supportEmail(env: Record<string, string | undefined> = process.env): string {
  return env.SUPPORT_EMAIL ?? "";
}
