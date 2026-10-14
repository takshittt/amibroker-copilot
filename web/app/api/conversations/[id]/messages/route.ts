import { forward } from "@/lib/server/forward";
import { config, notFound, safeId } from "@/lib/server/routes";

export const dynamic = "force-dynamic";
// An answer can take about 45 seconds; the real limit depends on the Vercel plan.
export const maxDuration = 120;

export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  const id = safeId((await context.params).id);
  if (!id) return notFound();
  return forward(request, `/v1/conversations/${id}/messages`, config(), {
    auth: true,
    stream: true,
  });
}
