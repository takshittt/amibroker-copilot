"use client";

import { useCallback, useEffect, useState } from "react";
import { getJson } from "@/lib/client";
import styles from "./Chrome.module.css";

type Usage = { used: number; limit: number; remaining: number; resets_at: string };

export const USAGE_CHANGED = "afl-usage-changed";

/** Answers left today. Updates when an answer finishes. */
export function UsageMeter() {
  const [usage, setUsage] = useState<Usage | null>(null);
  const load = useCallback(() => {
    getJson<Usage>("/api/usage")
      .then(setUsage)
      .catch(() => setUsage(null));
  }, []);
  useEffect(() => {
    load();
    window.addEventListener(USAGE_CHANGED, load);
    return () => window.removeEventListener(USAGE_CHANGED, load);
  }, [load]);
  if (!usage) return null;
  return (
    <span className={styles.usage} data-empty={usage.remaining === 0 || undefined}>
      {usage.remaining} of {usage.limit} answers left today
    </span>
  );
}
