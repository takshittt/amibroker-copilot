import { clearedCookie, isSecure, jsonError, sameOrigin } from "@/lib/server/forward";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  if (!sameOrigin(request)) {
    return jsonError(403, "forbidden", "This request did not come from the AFL Copilot website.");
  }
  return new Response(null, {
    status: 204,
    headers: { "Set-Cookie": clearedCookie(isSecure(request)) },
  });
}
