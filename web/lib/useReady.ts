"use client";

import { useEffect, useState } from "react";

/**
 * False until the page's script is running. Buttons that need the script
 * stay disabled until then, so an early click is never silently lost.
 */
export function useReady(): boolean {
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
  return ready;
}
