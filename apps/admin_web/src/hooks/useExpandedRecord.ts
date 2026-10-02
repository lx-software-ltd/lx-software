import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { isRowExpandedParam } from "../lib/expandedRecord";

type PendingExpand = {
  readonly id: string | null;
  readonly commit: () => void;
};

function writeParam(prev: URLSearchParams, param: string, id: string | null): URLSearchParams {
  const next = new URLSearchParams(prev);
  for (const key of [...next.keys()]) {
    if (key !== param && isRowExpandedParam(key)) next.delete(key);
  }
  if (id) next.set(param, id);
  else next.delete(param);
  return next;
}

/**
 * One open record at a time, synced to a query parameter.
 * `request` asks before discarding a dirty editor.
 */
export function useExpandedRecord(param: string) {
  const [params, setParams] = useSearchParams();
  const expandedId = params.get(param);
  const [pending, setPending] = useState<PendingExpand | null>(null);
  const expandedRef = useRef(expandedId);
  useEffect(() => {
    expandedRef.current = expandedId;
  }, [expandedId]);

  const apply = useCallback(
    (id: string | null, commit?: () => void) => {
      expandedRef.current = id;
      setParams((prev) => writeParam(prev, param, id), { replace: true });
      commit?.();
    },
    [param, setParams],
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
