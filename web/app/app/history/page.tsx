import type { Metadata } from "next";
import { HistoryList } from "@/components/HistoryList";

export const metadata: Metadata = { title: "History · AFL Copilot" };

export default function History() {
  return <HistoryList />;
}
