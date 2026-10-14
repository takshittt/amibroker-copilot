import { forwardLogin } from "@/lib/server/forward";
import { config } from "@/lib/server/routes";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  return forwardLogin(request, "/v1/auth/login", config());
}
