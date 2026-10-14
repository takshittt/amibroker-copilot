import type { Metadata } from "next";
import { AuthForm } from "@/components/AuthForm";

export const metadata: Metadata = { title: "Create an account · AFL Copilot" };

export default function Signup() {
  return <AuthForm mode="signup" />;
}
