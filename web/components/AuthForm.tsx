"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, postJson } from "@/lib/client";
import { useReady } from "@/lib/useReady";
import styles from "./AuthForm.module.css";

export function AuthForm({
  mode,
  supportEmail,
}: {
  mode: "login" | "signup";
  supportEmail?: string;
}) {
  const router = useRouter();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const ready = useReady();
  const signup = mode === "signup";

  async function submit(form: FormData) {
    setBusy(true);
    setError("");
    try {
      await postJson(signup ? "/api/auth/signup" : "/api/auth/login", {
        ...(signup ? { name: String(form.get("name") ?? "") } : {}),
        email: String(form.get("email") ?? ""),
        password: String(form.get("password") ?? ""),
      });
      router.push("/app");
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "Something went wrong. Please try again.",
      );
      setBusy(false);
    }
  }

  return (
    <main className={styles.page}>
      <Link href="/" className={styles.wordmark}>
        AFL Copilot
      </Link>
      <form
        className={styles.form}
        action={submit}
        aria-describedby={error ? "form-error" : undefined}
      >
        <h1>{signup ? "Create your account" : "Log in"}</h1>
        {signup ? (
          <label>
            Your name
            <input name="name" autoComplete="name" required maxLength={100} />
          </label>
        ) : null}
        <label>
          Email
          <input name="email" type="email" autoComplete="email" required maxLength={254} />
        </label>
        <label>
          Password
          <input
            name="password"
            type="password"
            autoComplete={signup ? "new-password" : "current-password"}
            required
            minLength={signup ? 10 : undefined}
            maxLength={128}
          />
          {signup ? (
            <span className={styles.hint}>
              At least 10 characters. A short sentence works well.
            </span>
          ) : null}
        </label>
        {error ? (
          <p id="form-error" className={styles.error} role="alert">
            {error}
          </p>
        ) : null}
        <button type="submit" className={styles.submit} disabled={busy || !ready}>
          {busy
            ? signup
              ? "Creating your account…"
              : "Logging in…"
            : signup
              ? "Create account"
              : "Log in"}
        </button>
        {signup ? (
          <p className={styles.switch}>
            Already have an account? <Link href="/login">Log in</Link>
          </p>
        ) : (
          <>
            <p className={styles.switch}>
              New here? <Link href="/signup">Create an account</Link>
            </p>
            <p className={styles.switch}>
              Forgot your password?{" "}
              {supportEmail ? (
                <>
                  Write to <a href={`mailto:${supportEmail}`}>{supportEmail}</a> from the address
                  you signed up with, and we will send you a new one.
                </>
              ) : (
                "Contact us from the address you signed up with, and we will send you a new one."
              )}
            </p>
          </>
        )}
      </form>
    </main>
  );
}
