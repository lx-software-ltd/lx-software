import { useCallback, useEffect, useRef, useState } from "react";
import { DRAFT_RECORD_ID } from "../lib/expandedRecord";
import { useExpandedRecord } from "./useExpandedRecord";
import { useHydrateExpandedRecord } from "./useHydrateExpandedRecord";

function structuralEqual(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((item, index) => structuralEqual(item, b[index]));
  }
  const left = a as Record<string, unknown>;
  const right = b as Record<string, unknown>;
  const leftKeys = Object.keys(left);
  const rightKeys = Object.keys(right);
  if (leftKeys.length !== rightKeys.length) return false;
  return leftKeys.every((key) => structuralEqual(left[key], right[key]));
}

export type RecordEditor<TForm, TRecord> = {
  readonly form: TForm;
  readonly setForm: (next: TForm | ((prev: TForm) => TForm)) => void;
  readonly formError: string | null;
  readonly setFormError: (message: string | null) => void;
  readonly editingId: string | null;
  readonly editingRecord: TRecord | null;
  readonly formOpen: boolean;
  readonly dirty: boolean;
  readonly expandedId: string | null;
  readonly confirmOpen: boolean;
  readonly pendingDeleteId: string | null;
  readonly openEdit: (record: TRecord) => void;
  readonly openCreate: () => void;
  readonly request: (id: string | null, commit?: () => void) => void;
  readonly resetFields: () => void;
  readonly applyRecord: (record: TRecord) => void;
  readonly requestDelete: (id: string) => void;
  readonly confirmDelete: () => void;
  readonly cancelDelete: () => void;
  readonly acceptPending: () => void;
  readonly cancelPending: () => void;
  /** Close the editor without asking, after a successful save. */
  readonly close: () => void;
};

export function useRecordEditor<TForm, TRecord>(options: {
  readonly param: string;
  readonly records: readonly TRecord[];
  readonly idOf?: (record: TRecord) => string;
  readonly emptyForm: () => TForm;
  readonly lineToForm: (record: TRecord) => TForm;
  readonly extraDirty?: boolean;
  readonly recordsReady?: boolean;
  readonly onDelete: (id: string) => void;
  readonly onReset?: () => void;
  readonly onApply?: (record: TRecord) => void;
}): RecordEditor<TForm, TRecord> {
  const idOf = options.idOf ?? ((record: TRecord) => (record as { id: string }).id);
  const expanded = useExpandedRecord(options.param);
  const emptyFormRef = useRef(options.emptyForm);
  const lineToFormRef = useRef(options.lineToForm);
  const onDeleteRef = useRef(options.onDelete);
  const onResetRef = useRef(options.onReset);
  const onApplyRef = useRef(options.onApply);
  const idOfRef = useRef(idOf);
  useEffect(() => {
    emptyFormRef.current = options.emptyForm;
    lineToFormRef.current = options.lineToForm;
    onDeleteRef.current = options.onDelete;
    onResetRef.current = options.onReset;
    onApplyRef.current = options.onApply;
    idOfRef.current = idOf;
  });

  const [form, setForm] = useState<TForm>(() => options.emptyForm());
  const [formError, setFormError] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

  const editingId =
    expanded.expandedId && expanded.expandedId !== DRAFT_RECORD_ID ? expanded.expandedId : null;
  const formOpen = expanded.expandedId !== null;
  const editingRecord = editingId
    ? (options.records.find((record) => idOf(record) === editingId) ?? null)
    : null;

  const baseline = editingRecord ? options.lineToForm(editingRecord) : options.emptyForm();
  const fieldsDirty =
    editingId !== null && editingRecord === null ? false : !structuralEqual(form, baseline);
  const dirty = formOpen && (Boolean(options.extraDirty) || fieldsDirty);
  const dirtyRef = useRef(dirty);
  useEffect(() => {
    dirtyRef.current = dirty;
  });

  const resetFields = useCallback(() => {
    setFormError(null);
    setForm(emptyFormRef.current());
    onResetRef.current?.();
  }, []);

  const fillForm = useCallback((record: TRecord) => {
    setFormError(null);
    setForm(lineToFormRef.current(record));
  }, []);

  const applyRecord = useCallback(
    (record: TRecord) => {
      fillForm(record);
      onApplyRef.current?.(record);
    },
    [fillForm],
  );

  useHydrateExpandedRecord({
    expandedId: expanded.expandedId,
    recordsReady: options.recordsReady ?? true,
    record: editingRecord,
    apply: fillForm,
    onMissing: () => expanded.request(null, false),
  });

  const openEdit = useCallback(
    (record: TRecord) => {
      expanded.toggle(idOfRef.current(record), dirtyRef.current, () => applyRecord(record), resetFields);
    },
    [applyRecord, expanded, resetFields],
  );

  const openCreate = useCallback(() => {
    if (expanded.expandedId === DRAFT_RECORD_ID) {
      expanded.request(null, dirtyRef.current, resetFields);
      return;
    }
    expanded.request(DRAFT_RECORD_ID, dirtyRef.current, resetFields);
  }, [expanded, resetFields]);

  const request = useCallback(
    (id: string | null, commit?: () => void) => {
      expanded.request(id, dirtyRef.current, commit);
    },
    [expanded],
  );

  const close = useCallback(() => {
    resetFields();
    expanded.request(null, false);
  }, [expanded, resetFields]);

  const confirmDelete = useCallback(() => {
    const id = pendingDeleteId;
    if (!id) return;
    setPendingDeleteId(null);
    onDeleteRef.current(id);
    if (expanded.expandedId === id) {
      resetFields();
      expanded.request(null, false);
    }
  }, [expanded, pendingDeleteId, resetFields]);

  return {
    form,
    setForm,
    formError,
    setFormError,
    editingId,
    editingRecord,
    formOpen,
    dirty,
    expandedId: expanded.expandedId,
    confirmOpen: expanded.confirmOpen,
    pendingDeleteId,
    openEdit,
    openCreate,
    request,
    resetFields,
    applyRecord,
    requestDelete: setPendingDeleteId,
    confirmDelete,
    cancelDelete: () => setPendingDeleteId(null),
    acceptPending: expanded.acceptPending,
    cancelPending: expanded.cancelPending,
    close,
  };
}
