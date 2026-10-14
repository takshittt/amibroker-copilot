"use client";

import { useRouter } from "next/navigation";
import styles from "./Chrome.module.css";

export function LogoutButton() {
  const router = useRouter();
  return (
    <button
      type="button"
      className={styles.link}
      onClick={async () => {
        await fetch("/api/auth/logout", { method: "POST" });
        router.push("/");
        router.refresh();
      }}
    >
      Log out
    </button>
  );
}
