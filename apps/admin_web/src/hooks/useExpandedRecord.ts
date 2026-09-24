import { useCallback, useRef, useState } from "react";
import {
  readExpandedParam,
  writeExpandedParam,
} from "../lib/expandedRecord";

type PendingExpand = {
  readonly id: string | null;
  readonly commit: () => void;
};

/**
 * One open record at a time, synced to a query parameter.
 * `request` asks before discarding a dirty editor.
 */
export function useExpandedRecord(param: string) {
  const [expandedId, setExpandedId] = useState<string | null>(() => readExpandedParam(param));
  const [pending, setPending] = useState<PendingExpand | null>(null);
  const expandedRef = useRef(expandedId);

  const apply = useCallback(
    (id: string | null, commit?: () => void) => {
      expandedRef.current = id;
      setExpandedId(id);
      writeExpandedParam(param, id);
      commit?.();
    },
    [param],
  );

  const request = useCallback(
    (id: string | null, dirty: boolean, commit?: () => void) => {
      if (expandedRef.current === id) return;
      if (dirty && expandedRef.current !== null) {
        setPending({ id, commit: commit ?? (() => undefined) });
        return;
      }
      apply(id, commit);
    },
    [apply],
  );

  const toggle = useCallback(
    (id: string, dirty: boolean, onOpen: () => void, onClose: () => void) => {
      if (expandedRef.current === id) request(null, dirty, onClose);
      else request(id, dirty, onOpen);
    },
    [request],
  );

  const acceptPending = useCallback(() => {
    if (!pending) return;
    const next = pending;
    setPending(null);
    apply(next.id, next.commit);
  }, [apply, pending]);

  const cancelPending = useCallback(() => {
    setPending(null);
  }, []);

  return {
    expandedId,
    request,
    toggle,
    acceptPending,
    cancelPending,
    confirmOpen: pending !== null,
  };
}
