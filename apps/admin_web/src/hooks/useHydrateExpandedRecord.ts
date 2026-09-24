import { useEffect, useRef, useState } from "react";
import { DRAFT_RECORD_ID } from "../lib/expandedRecord";

/**
 * Copies a deep-linked record into the editor once, before paint.
 * An id that is not in the loaded list is cleared after commit so the URL
 * write does not happen during render.
 */
export function useHydrateExpandedRecord<T>(options: {
  readonly expandedId: string | null;
  /** False while the list that would contain the record is still loading. */
  readonly recordsReady: boolean;
  readonly record: T | null;
  readonly apply: (record: T) => void;
  readonly onMissing: () => void;
}): void {
  const { expandedId, recordsReady, record, apply, onMissing } = options;
  const [hydratedId, setHydratedId] = useState<string | null>(null);
  const targetId = expandedId && expandedId !== DRAFT_RECORD_ID ? expandedId : null;

  if (!targetId) {
    if (hydratedId !== null) setHydratedId(null);
  } else if (record && hydratedId !== targetId) {
    setHydratedId(targetId);
    apply(record);
  }

  const missing = targetId !== null && recordsReady && record === null;
  const onMissingRef = useRef(onMissing);
  useEffect(() => {
    onMissingRef.current = onMissing;
  });
  useEffect(() => {
    if (!missing || !targetId) return;
    onMissingRef.current();
  }, [missing, targetId]);
}
