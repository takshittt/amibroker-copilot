import { forward } from "@/lib/server/forward";
import { config } from "@/lib/server/routes";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  return forward(request, "/v1/conversations", config(), { auth: true });
}

export async function POST(request: Request) {
  return forward(request, "/v1/conversations", config(), { auth: true });
}
