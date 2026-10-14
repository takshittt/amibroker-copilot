"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, getJson } from "@/lib/client";
import styles from "./HistoryList.module.css";

type Row = {
  id: string;
  mode: string;
  market_id: string;
  timeframe: string;
  title: string;
  created_at: string;
};

const MODE_NAMES: Record<string, string> = {
  write: "Write",
  review: "Review",
  fix: "Fix an error",
};

export function HistoryList() {
  const router = useRouter();
  const [rows, setRows] = useState<Row[] | null>(null);

  useEffect(() => {
    getJson<Row[]>("/api/conversations")
      .then(setRows)
      .catch((caught) => {
        if (caught instanceof ApiError && caught.status === 401) router.push("/login");
        else setRows([]);
      });
  }, [router]);

  if (rows === null) return <p>Loading your history…</p>;
  if (rows.length === 0) {
    return (
      <section className={styles.empty}>
        <h1>History</h1>
        <p>
          Nothing here yet. <Link href="/app">Write your first strategy</Link> and it will be kept
          here.
        </p>
      </section>
    );
  }
  return (
    <section>
      <h1 className={styles.title}>History</h1>
      <ul className={styles.list}>
        {rows.map((row) => (
          <li key={row.id}>
            <Link href={`/app/c/${row.id}`} className={styles.row}>
              <span className={styles.name}>{row.title || "Untitled"}</span>
              <span className={styles.meta}>
                {MODE_NAMES[row.mode] ?? row.mode}, {row.market_id}, {row.timeframe},{" "}
                {new Date(row.created_at).toLocaleDateString(undefined, {
                  day: "numeric",
                  month: "short",
                })}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
