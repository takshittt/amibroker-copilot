/** The session token in its cookie: checked here before anything is forwarded. */

import { jwtVerify } from "jose";

export type Session = { userId: string; token: string };

/**
 * The signed-in user, or null. Only HS256 is accepted, the signature and
 * expiry must be valid, and the token must name a user.
 */
export async function readSession(
  token: string | undefined,
  jwtSecret: string,
): Promise<Session | null> {
  if (!token) return null;
  try {
    const { payload } = await jwtVerify(token, new TextEncoder().encode(jwtSecret), {
      algorithms: ["HS256"],
      requiredClaims: ["sub", "exp", "iat"],
    });
    if (typeof payload.sub !== "string" || payload.sub === "") return null;
    return { userId: payload.sub, token };
  } catch {
    return null;
  }
}
