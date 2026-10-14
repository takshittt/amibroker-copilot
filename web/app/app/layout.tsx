import { cookies } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";
import { LogoutButton } from "@/components/LogoutButton";
import { UsageMeter } from "@/components/UsageMeter";
import { SESSION_COOKIE, serverConfig } from "@/lib/server/config";
import { readSession } from "@/lib/server/session";
import styles from "./app.module.css";

/** Everything under /app needs a valid session; without one, log in first. */
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  const session = await readSession(token, serverConfig().jwtSecret);
  if (!session) redirect("/login");
  return (
    <div className={styles.shell}>
      <header className={styles.bar}>
        <Link href="/app" className={styles.wordmark}>
          AFL Copilot
        </Link>
        <nav className={styles.nav} aria-label="Main">
          <Link href="/app">New</Link>
          <Link href="/app/history">History</Link>
          <UsageMeter />
          <LogoutButton />
        </nav>
      </header>
      {children}
    </div>
  );
}
