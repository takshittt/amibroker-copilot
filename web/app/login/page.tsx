import type { Metadata } from "next";
import { AuthForm } from "@/components/AuthForm";
import { supportEmail } from "@/lib/server/config";

export const metadata: Metadata = { title: "Log in · AFL Copilot" };
// Read the support address when the page is served, not when the site is built.
export const dynamic = "force-dynamic";

export default function Login() {
  return <AuthForm mode="login" supportEmail={supportEmail()} />;
}
