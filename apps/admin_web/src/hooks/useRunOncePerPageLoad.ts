import { useEffect, useRef } from "react";

const startedKeys = new Set<string>();

/**
 * Runs `fn` once per full page load for `key`. A later effect run in the same
 * document (including React strict-mode remount) is skipped. `fn` may return a
 * cleanup; that cleanup still runs if the effect is torn down.
 */
export function useRunOncePerPageLoad(key: string, fn: () => void | (() => void)): void {
  const fnRef = useRef(fn);
  useEffect(() => {
    fnRef.current = fn;
  });
  useEffect(() => {
    if (startedKeys.has(key)) return;
    startedKeys.add(key);
    return fnRef.current();
  }, [key]);
}
