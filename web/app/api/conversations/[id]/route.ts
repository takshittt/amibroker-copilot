import { forward } from "@/lib/server/forward";
import { config, notFound, safeId } from "@/lib/server/routes";

export const dynamic = "force-dynamic";

export async function GET(request: Request, context: { params: Promise<{ id: string }> }) {
  const id = safeId((await context.params).id);
  if (!id) return notFound();
  return forward(request, `/v1/conversations/${id}`, config(), { auth: true });
}
