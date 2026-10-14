import type { Metadata } from "next";
import { ConversationLoader } from "@/components/ConversationLoader";

export const metadata: Metadata = { title: "Conversation · AFL Copilot" };

export default async function ConversationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ConversationLoader id={id} />;
}
