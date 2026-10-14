import type { Metadata } from "next";
import { Chat } from "@/components/Chat";

export const metadata: Metadata = { title: "New · AFL Copilot" };

export default function NewConversation() {
  return <Chat />;
}
