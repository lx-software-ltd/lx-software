import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  coerceSupportedCurrency,
  type CurrencyCode,
} from "../lib/currencies";
import { AdminApiError, fetchAssetDownloadUrl } from "../lib/apiAdminClient";
import {
  newStatementLineId,
  type FinanceLineType,
  type HouseFinanceData,
  type HouseStatementLine,
  type StatementOwnerKey,
  statementLineAssetKeys,
} from "../lib/financeModel";
import { formatDateUtc } from "../lib/formatDisplay";
import { parseAmount } from "../lib/formParse";
import { DRAFT_RECORD_ID } from "../lib/expandedRecord";
import { useExpandedRecord } from "../hooks/useExpandedRecord";
import {
  existingImportedStatementBasenames,
  useParseStatement,
} from "../hooks/useParseStatement";
import { uploadFinanceAsset } from "../lib/uploadFinanceAsset";
import {
  AdminCell,
  AdminDataTable,
  AdminDataTableCellMeta,
  AdminDataTableEmptyRow,
  type AdminDataTableColumn,
  AdminCreateButton,
  AdminDisclosure,
  AdminEditorPanel,
  AdminEditorSection,
  AdminExpandableRow,
  AdminFilterBar,
  AdminFilterField,
  AdminRecordTable,
  AdminRowActions,
  ConfirmDialog,
  CurrencySelect,
  MoneyAmount,
} from "./ui";

function utcPartsFromIso(iso: string): { datePart: string; timePart: string } {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    const now = new Date();
    return {
      datePart: now.toISOString().slice(0, 10),
      timePart: now.toISOString().slice(11, 16),
    };
  }
  return {
    datePart: d.toISOString().slice(0, 10),
    timePart: d.toISOString().slice(11, 16),
  };
}

function isoFromUtcParts(datePart: string, timePart: string): string {
  const t = timePart.length >= 5 ? timePart.slice(0, 5) : "00:00";
  return `${datePart}T${t}:00.000Z`;
}

function statementLineTypeLabel(
  type: FinanceLineType,
  lockedLineType?: Extract<FinanceLineType, "income" | "expenditure">,
): string {
  if (type === "income") return lockedLineType === "income" ? "Gain" : "Income";
  if (type === "mortgage") return "Mortgage";
  return lockedLineType === "expenditure" ? "Expense" : "Expenditure";
}

function statementLineTypeClass(type: FinanceLineType): string {
  return type === "income" ? "text-success" : "text-danger";
}

function basenameFromAssetKey(key: string): string {
  const parts = key.trim().split("/");
  return parts[parts.length - 1] || key.trim();
}

function dedupeAssetKeys(keys: readonly string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const k of keys) {
    const t = k.trim();
    if (!t || seen.has(t)) continue;
    seen.add(t);
    out.push(t);
  }
  return out;
}

/** Opens stored statement files in a new tab via a presigned URL (same pattern as Assets). */
function StatementAssetLaunchButton({
  assetKey,
  openingPdfKey,
  onOpen,
}: {
  readonly assetKey: string;
  readonly openingPdfKey: string | null;
  readonly onOpen: (key: string) => void;
}) {
  const busy = openingPdfKey === assetKey;
  const base = basenameFromAssetKey(assetKey);
  const isPdf = base.toLowerCase().endsWith(".pdf");
  return (
    <button
      type="button"
      className="badge text-bg-light border align-middle btn btn-sm lh-base"
      title={`Open attachment (${base})`}
      aria-label={`Open attachment ${base}`}
      disabled={busy}
      onClick={(event) => {
        event.stopPropagation();
        onOpen(assetKey);
      }}
    >
      {busy ? (
        <span
          className="spinner-border spinner-border-sm"
          role="status"
          aria-hidden="true"
        />
      ) : (
        <>
          <i
            className={`bi me-1 ${isPdf ? "bi-file-earmark-pdf" : "bi-file-earmark"}`}
            aria-hidden="true"
          />
          {isPdf ? "PDF" : "File"}
        </>
      )}
    </button>
  );
}

function emptyLineForm(defaultCurrency: CurrencyCode): LineFormState {
  const datePart = new Date().toISOString().slice(0, 10);
  return {
    datePart,
    timePart: "00:00",
    type: "expenditure",
    description: "",
    netAmount: "",
    vat: "",
    grossAmount: "",
    currency: defaultCurrency,
  };
}

type LineFormState = {
  datePart: string;
  timePart: string;
  type: FinanceLineType;
  description: string;
  netAmount: string;
  vat: string;
  grossAmount: string;
  currency: string;
};

function lineToForm(line: HouseStatementLine): LineFormState {
  const { datePart, timePart } = utcPartsFromIso(line.dateUtc);
  return {
    datePart,
    timePart,
    type: line.type,
    description: line.description,
    netAmount: String(line.netAmount),
    vat: String(line.vat),
    grossAmount: String(line.grossAmount),
    currency: line.currency,
  };
}

export type HouseStatementPanelProps = {
  readonly houseKey: StatementOwnerKey;
  readonly data: HouseFinanceData;
  readonly onPatch: (patch: (prev: HouseFinanceData) => HouseFinanceData) => void;
  /** When set, the editor and table only handle this line type. */
  readonly lockedLineType?: Extract<FinanceLineType, "income" | "expenditure">;
  readonly showHouseDetails?: boolean;
  readonly showMortgageImport?: boolean;
  readonly importTitle?: string;
  readonly importDescription?: string;
  readonly lineSectionTitle?: string;
  readonly tableSectionTitle?: string;
  readonly emptyMessage?: string;
  readonly importFileLabel?: string;
};

const TABLE_COLUMNS: AdminDataTableColumn[] = [
  { key: "when", header: "Date (UTC)", className: "small", priority: "secondary" },
  { key: "type", header: "Type", className: "small", priority: "secondary" },
  { key: "desc", header: "Description", className: "small" },
  {
    key: "net",
    header: "Net",
    className: "small text-end",
    headerClassName: "small text-end",
    priority: "tertiary",
  },
  {
    key: "vat",
    header: "VAT",
    className: "small text-end",
    headerClassName: "small text-end",
    priority: "tertiary",
  },
  { key: "ccy", header: "Currency", className: "small", priority: "secondary" },
  {
    key: "gross",
    header: "Gross",
    className: "small text-end",
    headerClassName: "small text-end",
  },
  {
    key: "ops",
    header: <span className="visually-hidden">Operations</span>,
    className: "text-end admin-nowrap",
    headerClassName: "text-end",
  },
];

const COL_SPAN = TABLE_COLUMNS.length;

export function HouseStatementPanel({
  houseKey,
  data,
  onPatch,
  lockedLineType,
  showHouseDetails = true,
  showMortgageImport = true,
  importTitle = "Import statement (PDF)",
  importDescription = "Upload a statement PDF (or image). The file is stored under Assets and the contents are sent to OpenRouter to extract each transaction as a new statement line.",
  lineSectionTitle = "Statement line",
  tableSectionTitle = "House statement",
  emptyMessage = "No statement lines yet.",
  importFileLabel = "Statement file",
}: HouseStatementPanelProps) {
  const lineFormId = `${houseKey}-line-form`;
  const [floatAmount, setFloatAmount] = useState(String(data.float.amount));
  const [floatCurrency, setFloatCurrency] = useState(() =>
    coerceSupportedCurrency(data.float.currency, data.defaultCurrency),
  );
  const [houseDefaultDraft, setHouseDefaultDraft] = useState(data.defaultCurrency);

  const expanded = useExpandedRecord(`${houseKey}-line`);
  const editingId =
    expanded.expandedId && expanded.expandedId !== DRAFT_RECORD_ID
      ? expanded.expandedId
      : null;
  const formOpen = expanded.expandedId !== null;
  const [formError, setFormError] = useState<string | null>(null);
  const [lineForm, setLineForm] = useState<LineFormState>(() => {
    const next = emptyLineForm(data.defaultCurrency);
    return lockedLineType ? { ...next, type: lockedLineType } : next;
  });
  const [tableFilter, setTableFilter] = useState("");

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const linePdfInputRef = useRef<HTMLInputElement | null>(null);
  const lineDescriptionRef = useRef<HTMLInputElement | null>(null);
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [importMortgageOnly, setImportMortgageOnly] = useState(false);
  const [parseSuccess, setParseSuccess] = useState<string | null>(null);
  const [openingPdfKey, setOpeningPdfKey] = useState<string | null>(null);
  const parseStatement = useParseStatement(houseKey);
  const queryClient = useQueryClient();

  const [pendingLineFiles, setPendingLineFiles] = useState<File[]>([]);
  const [removedAssetKeys, setRemovedAssetKeys] = useState<string[]>([]);
  /** When duplicating into the editor (add mode), attachment keys copied from the source line. */
  const [prefillStatementAssetKeys, setPrefillStatementAssetKeys] = useState<
    string[] | null
  >(null);
  const [lineSubmitBusy, setLineSubmitBusy] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [statementPdfOpenError, setStatementPdfOpenError] = useState<string | null>(null);

  useEffect(() => {
    queueMicrotask(() => {
      setFloatAmount(String(data.float.amount));
      setFloatCurrency(
        coerceSupportedCurrency(data.float.currency, data.defaultCurrency),
      );
      setHouseDefaultDraft(data.defaultCurrency);
    });
  }, [data.float.amount, data.float.currency, data.defaultCurrency]);

  useEffect(() => {
    if (editingId !== null) return;
    if (prefillStatementAssetKeys !== null) return;
    queueMicrotask(() => {
      setLineForm((f) => ({ ...f, currency: data.defaultCurrency }));
    });
  }, [data.defaultCurrency, editingId, prefillStatementAssetKeys]);

  const scopedLines = useMemo(() => {
    if (!lockedLineType) return data.lines;
    return data.lines.filter((line) => line.type === lockedLineType);
  }, [data.lines, lockedLineType]);

  const sortedLines = useMemo(() => {
    return [...scopedLines].sort((a, b) => {
      const ta = new Date(a.dateUtc).getTime();
      const tb = new Date(b.dateUtc).getTime();
      return tb - ta;
    });
  }, [scopedLines]);

  const filteredLines = useMemo(() => {
    const q = tableFilter.trim().toLowerCase();
    if (!q) return sortedLines;
    return sortedLines.filter((line) => {
      const hay = [
        line.description,
        line.type,
        line.currency,
        String(line.netAmount),
        String(line.vat),
        String(line.grossAmount),
        line.dateUtc.slice(0, 10),
        formatDateUtc(line.dateUtc),
        ...statementLineAssetKeys(line).flatMap((k) => [k, basenameFromAssetKey(k)]),
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [sortedLines, tableFilter]);

  const editingLine =
    editingId === null ? undefined : data.lines.find((l) => l.id === editingId);
  const baseStatementAttachmentKeys =
    editingId !== null
      ? editingLine === undefined
        ? []
        : [...statementLineAssetKeys(editingLine)]
      : (prefillStatementAssetKeys ?? []);
  const keptAttachmentKeys = baseStatementAttachmentKeys.filter(
    (k) => !removedAssetKeys.includes(k),
  );

  function applyHouseDetails() {
    const amt = parseAmount(floatAmount);
    if (amt === null) {
      return;
    }
    const nextDefault = coerceSupportedCurrency(
      houseDefaultDraft,
      data.defaultCurrency,
    );
    const floatCur = coerceSupportedCurrency(floatCurrency, nextDefault);
    onPatch((prev) => ({
      ...prev,
      defaultCurrency: nextDefault,
      float: { amount: amt, currency: floatCur },
    }));
    setHouseDefaultDraft(nextDefault);
    setFloatAmount(String(amt));
    setFloatCurrency(floatCur);
  }

  function blankLineForm() {
    const next = emptyLineForm(data.defaultCurrency);
    return lockedLineType ? { ...next, type: lockedLineType } : next;
  }

  const [hydratedLineId, setHydratedLineId] = useState<string | null>(null);
  if (!editingId) {
    if (hydratedLineId !== null) setHydratedLineId(null);
  } else if (editingLine && hydratedLineId !== editingId) {
    setHydratedLineId(editingId);
    setLineForm((current) => {
      const saved = lineToForm(editingLine);
      const blank = blankLineForm();
      if (JSON.stringify(current) === JSON.stringify(blank)) return saved;
      return current;
    });
  } else if (!editingLine && hydratedLineId !== editingId) {
    setHydratedLineId(editingId);
    expanded.request(null, false);
  }

  function resetLineFields() {
    setFormError(null);
    setLineForm(blankLineForm());
    setPendingLineFiles([]);
    setRemovedAssetKeys([]);
    setPrefillStatementAssetKeys(null);
    if (linePdfInputRef.current) {
      linePdfInputRef.current.value = "";
    }
  }

  function applyLineToForm(line: HouseStatementLine, duplicate: boolean) {
    setFormError(null);
    setLineForm(lineToForm(line));
    setPendingLineFiles([]);
    setRemovedAssetKeys([]);
    setPrefillStatementAssetKeys(
      duplicate ? dedupeAssetKeys(statementLineAssetKeys(line)) : null,
    );
    if (linePdfInputRef.current) {
      linePdfInputRef.current.value = "";
    }
    queueMicrotask(() => lineDescriptionRef.current?.focus());
  }

  function lineDirty(): boolean {
    if (!formOpen) return false;
    if (pendingLineFiles.length > 0 || removedAssetKeys.length > 0) return true;
    if (prefillStatementAssetKeys !== null) return true;
    if (editingId) {
      const line = data.lines.find((row) => row.id === editingId);
      if (!line) return false;
      return JSON.stringify(lineForm) !== JSON.stringify(lineToForm(line));
    }
    return JSON.stringify(lineForm) !== JSON.stringify(blankLineForm());
  }

  function openEdit(line: HouseStatementLine) {
    expanded.toggle(
      line.id,
      lineDirty(),
      () => applyLineToForm(line, false),
      resetLineFields,
    );
  }

  function openDuplicateIntoEditor(line: HouseStatementLine) {
    expanded.request(DRAFT_RECORD_ID, lineDirty(), () => applyLineToForm(line, true));
  }

  function openCreate() {
    if (expanded.expandedId === DRAFT_RECORD_ID) {
      expanded.request(null, lineDirty(), resetLineFields);
      return;
    }
    expanded.request(DRAFT_RECORD_ID, lineDirty(), resetLineFields);
  }

  async function submitLine(e: FormEvent) {
    e.preventDefault();
    const net = parseAmount(lineForm.netAmount);
    const vat = parseAmount(lineForm.vat);
    const gross = parseAmount(lineForm.grossAmount);
    if (!lineForm.description.trim()) {
      setFormError("Description is required.");
      return;
    }
    if (net === null || vat === null || gross === null) {
      setFormError("Net, VAT, and gross must be valid numbers.");
      return;
    }
    const currency = coerceSupportedCurrency(lineForm.currency, data.defaultCurrency);
    const dateUtc = isoFromUtcParts(lineForm.datePart, lineForm.timePart);

    const basenames = existingImportedStatementBasenames(data, editingId ?? undefined);
    const pendingNames = new Set<string>();
    for (const f of pendingLineFiles) {
      if (pendingNames.has(f.name)) {
        setFormError(
          `You added "${f.name}" more than once. Remove duplicate staged files.`,
        );
        return;
      }
      pendingNames.add(f.name);
      if (basenames.has(f.name)) {
        setFormError(
          `A statement file named "${f.name}" is already linked to another line for this house. Remove it from that line or rename the file.`,
        );
        return;
      }
    }

    const uploadedKeys: string[] = [];
    if (pendingLineFiles.length > 0) {
      setLineSubmitBusy(true);
      setFormError(null);
      try {
        for (const file of pendingLineFiles) {
          uploadedKeys.push(await uploadFinanceAsset(file, houseKey, queryClient));
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setFormError(msg || "Could not upload a statement file.");
        return;
      } finally {
        setLineSubmitBusy(false);
      }
    }

    const sourceAssetKeys = dedupeAssetKeys([...keptAttachmentKeys, ...uploadedKeys]);

    const row: HouseStatementLine = {
      id: editingId ?? newStatementLineId(),
      dateUtc,
      type: lockedLineType ?? lineForm.type,
      description: lineForm.description.trim(),
      netAmount: net,
      vat,
      currency,
      grossAmount: gross,
      ...(sourceAssetKeys.length ? { sourceAssetKeys } : {}),
    };

    onPatch((prev) => {
      if (editingId) {
        return {
          ...prev,
          lines: prev.lines.map((l) => (l.id === editingId ? row : l)),
        };
      }
      return {
        ...prev,
        lines: [...prev.lines, row],
      };
    });

    resetLineFields();
    expanded.request(null, false);
  }

  function openStatementPdf(assetKey: string) {
    setStatementPdfOpenError(null);
    setOpeningPdfKey(assetKey);
    void fetchAssetDownloadUrl(assetKey)
      .then((url) => {
        // Same as Assets: open URL directly; blank+noopener tabs often get a null handle.
        window.open(url, "_blank", "noopener,noreferrer");
      })
      .catch((err) => {
        const msg =
          err instanceof AdminApiError
            ? err.responseBody || err.message
            : err instanceof Error
              ? err.message
              : "Could not open the file.";
        setStatementPdfOpenError(msg);
      })
      .finally(() => {
        setOpeningPdfKey(null);
      });
  }

  function deleteLine(id: string) {
    onPatch((prev) => ({
      ...prev,
      lines: prev.lines.filter((l) => l.id !== id),
    }));
    if (editingId === id) {
      resetLineFields();
      expanded.request(null, false);
    }
    setPendingDeleteId(null);
  }

      const lineEditor = formOpen ? (
        <AdminEditorPanel
          formId={lineFormId}
          onSubmit={submitLine}
          submitLabel={editingId ? "Update line" : "Add line"}
          isSaving={lineSubmitBusy}
          savingLabel="Uploading…"
          error={formError}
        >
          <span className="visually-hidden">{lineSectionTitle}</span>
          <div className="row g-3">
            <div className="col-12 col-sm-6 col-md-3">
              <label className="form-label small" htmlFor={`${houseKey}-fin-date-utc`}>
                Date (UTC)
              </label>
              <input
                id={`${houseKey}-fin-date-utc`}
                type="date"
                className="form-control form-control-sm"
                required
                value={lineForm.datePart}
                onChange={(ev) =>
                  setLineForm((f) => ({ ...f, datePart: ev.target.value }))
                }
              />
            </div>
            {lockedLineType ? null : (
            <div className="col-12 col-sm-6 col-md-3">
              <label className="form-label small" htmlFor={`${houseKey}-fin-type`}>
                Type
              </label>
              <select
                id={`${houseKey}-fin-type`}
                className="form-select form-select-sm"
                value={lineForm.type}
                onChange={(ev) =>
                  setLineForm((f) => ({
                    ...f,
                    type: ev.target.value as FinanceLineType,
                  }))
                }
              >
                <option value="income">Income</option>
                <option value="expenditure">Expenditure</option>
                <option value="mortgage">Mortgage</option>
              </select>
            </div>
            )}
            <div className="col-12 col-md-6">
              <label className="form-label small" htmlFor={`${houseKey}-fin-desc`}>
                Description
              </label>
              <input
                id={`${houseKey}-fin-desc`}
                ref={lineDescriptionRef}
                type="text"
                className="form-control form-control-sm"
                required
                value={lineForm.description}
                onChange={(ev) =>
                  setLineForm((f) => ({ ...f, description: ev.target.value }))
                }
              />
            </div>
            <div className="col-12 col-sm-6 col-md-3">
              <label className="form-label small" htmlFor={`${houseKey}-fin-net`}>
                Net amount
              </label>
              <input
                id={`${houseKey}-fin-net`}
                type="number"
                step="0.01"
                className="form-control form-control-sm"
                required
                value={lineForm.netAmount}
                onChange={(ev) =>
                  setLineForm((f) => ({ ...f, netAmount: ev.target.value }))
                }
              />
            </div>
            <div className="col-12 col-sm-6 col-md-3">
              <label className="form-label small" htmlFor={`${houseKey}-fin-vat`}>
                VAT
              </label>
              <input
                id={`${houseKey}-fin-vat`}
                type="number"
                step="0.01"
                className="form-control form-control-sm"
                required
                value={lineForm.vat}
                onChange={(ev) =>
                  setLineForm((f) => ({ ...f, vat: ev.target.value }))
                }
              />
            </div>
            <div className="col-12 col-sm-6 col-md-3">
              <label className="form-label small" htmlFor={`${houseKey}-fin-gross`}>
                Gross amount
              </label>
              <input
                id={`${houseKey}-fin-gross`}
                type="number"
                step="0.01"
                className="form-control form-control-sm"
                required
                value={lineForm.grossAmount}
                onChange={(ev) =>
                  setLineForm((f) => ({ ...f, grossAmount: ev.target.value }))
                }
              />
            </div>
            <div className="col-12 col-sm-6 col-md-3">
              <label className="form-label small" htmlFor={`${houseKey}-fin-cur`}>
                Currency
              </label>
              <CurrencySelect
                id={`${houseKey}-fin-cur`}
                value={lineForm.currency}
                onChange={(code) =>
                  setLineForm((f) => ({ ...f, currency: code }))
                }
              />
            </div>
            <div className="col-12">
              <label className="form-label small mb-1" htmlFor={`${houseKey}-line-pdf`}>
                Statement files{" "}
                <span className="text-muted fw-normal">(optional, PDF or images)</span>
              </label>
              <input
                id={`${houseKey}-line-pdf`}
                ref={linePdfInputRef}
                type="file"
                multiple
                accept="application/pdf,image/*"
                className="form-control form-control-sm"
                disabled={lineSubmitBusy}
                onChange={(ev) => {
                  const picked = ev.target.files ? Array.from(ev.target.files) : [];
                  setPendingLineFiles((prev) => [...prev, ...picked]);
                  setFormError(null);
                  ev.target.value = "";
                }}
              />
              {keptAttachmentKeys.length > 0 ? (
                <div className="small mt-2">
                  <div className="text-muted mb-1">Attached:</div>
                  <ul className="list-unstyled mb-0 d-flex flex-column gap-2">
                    {keptAttachmentKeys.map((key) => (
                      <li
                        key={key}
                        className="d-flex flex-wrap align-items-center gap-2"
                      >
                        <span className="fw-medium text-break">
                          {basenameFromAssetKey(key)}
                        </span>
                        <StatementAssetLaunchButton
                          assetKey={key}
                          openingPdfKey={openingPdfKey}
                          onOpen={openStatementPdf}
                        />
                        <button
                          type="button"
                          className="btn btn-outline-secondary btn-sm py-0"
                          disabled={lineSubmitBusy}
                          onClick={() =>
                            setRemovedAssetKeys((prev) =>
                              prev.includes(key) ? prev : [...prev, key],
                            )
                          }
                        >
                          Remove
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {pendingLineFiles.length > 0 ? (
                <div className="small mt-2">
                  <div className="text-muted mb-1">Staged uploads:</div>
                  <ul className="list-unstyled mb-0 d-flex flex-column gap-1">
                    {pendingLineFiles.map((file, idx) => (
                      <li
                        key={`${file.name}-${idx}-${file.size}`}
                        className="d-flex flex-wrap align-items-center gap-2"
                      >
                        <span className="text-break">{file.name}</span>
                        <button
                          type="button"
                          className="btn btn-outline-secondary btn-sm py-0"
                          disabled={lineSubmitBusy}
                          onClick={() =>
                            setPendingLineFiles((prev) =>
                              prev.filter((_, i) => i !== idx),
                            )
                          }
                        >
                          Remove
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {removedAssetKeys.length > 0 &&
              (editingId !== null || prefillStatementAssetKeys !== null) ? (
                <p className="small text-muted mb-0 mt-2">
                  Removed attachments are dropped when you save this line.
                </p>
              ) : null}
            </div>
          </div>
        </AdminEditorPanel>
      ) : null;

  return (
    <div>
      {statementPdfOpenError ? (
        <div
          className="alert alert-danger alert-dismissible py-2 small mb-3"
          role="alert"
        >
          <button
            type="button"
            className="btn-close"
            aria-label="Dismiss"
            onClick={() => setStatementPdfOpenError(null)}
          />
          {statementPdfOpenError}
        </div>
      ) : null}
      {showHouseDetails ? (
      <AdminEditorSection
        footer={
          <button type="button" className="btn btn-primary btn-sm" onClick={applyHouseDetails}>
            Save
          </button>
        }
      >
        <div className="row g-2 align-items-end flex-wrap">
          <div className="col-12 col-sm-6 col-md-auto admin-field-min">
            <label className="form-label small mb-0" htmlFor={`${houseKey}-house-default-ccy`}>
              Default currency
            </label>
            <CurrencySelect
              id={`${houseKey}-house-default-ccy`}
              value={houseDefaultDraft}
              onChange={(code) => {
                const next = coerceSupportedCurrency(code, data.defaultCurrency);
                setHouseDefaultDraft((prevDraft) => {
                  setFloatCurrency((fc) => (fc === prevDraft ? next : fc));
                  return next;
                });
              }}
              className="form-select form-select-sm"
            />
          </div>
        </div>
        <div className="row g-2 align-items-end flex-wrap mt-2">
          <div className="col-12 col-sm-6 col-md-auto">
            <label className="form-label small mb-0" htmlFor={`float-amt-${houseKey}`}>
              Float amount
            </label>
            <input
              id={`float-amt-${houseKey}`}
              type="number"
              className="form-control form-control-sm"
              step="0.01"
              value={floatAmount}
              onChange={(ev) => setFloatAmount(ev.target.value)}
            />
          </div>
          <div className="col-12 col-sm-6 col-md-auto admin-field-min">
            <label className="form-label small mb-0" htmlFor={`float-cur-${houseKey}`}>
              Float currency
            </label>
            <CurrencySelect
              id={`float-cur-${houseKey}`}
              value={floatCurrency}
              onChange={(code) => setFloatCurrency(code)}
              className="form-select form-select-sm"
            />
          </div>
        </div>
      </AdminEditorSection>
      ) : null}

      <AdminRecordTable
        label={tableSectionTitle}
        filters={
          <AdminFilterBar
            create={
              <AdminCreateButton
                label={
                  lockedLineType === "income"
                    ? "New gain"
                    : lockedLineType === "expenditure"
                      ? "New expense"
                      : "New line"
                }
                onClick={openCreate}
              />
            }
          >
            <AdminFilterField label="Filter" htmlFor={`${houseKey}-line-filter`}>
              <input
                id={`${houseKey}-line-filter`}
                type="search"
                className="form-control form-control-sm"
                placeholder="Filter lines…"
                autoComplete="off"
                value={tableFilter}
                onChange={(ev) => setTableFilter(ev.target.value)}
              />
            </AdminFilterField>
          </AdminFilterBar>
        }
        beforeTable={
          <AdminDisclosure title={importTitle}>
            <p className="small text-muted">{importDescription}</p>
            <AdminEditorSection
        embedded
        footer={
          <>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={!pdfFile || parseStatement.isPending}
              onClick={() => {
                if (!pdfFile) return;
                setParseSuccess(null);
                parseStatement.mutate(
                  {
                    file: pdfFile,
                    mortgageOnly: showMortgageImport && importMortgageOnly,
                    ...(lockedLineType ? { lineTypeOnly: lockedLineType } : {}),
                  },
                  {
                    onSuccess: (res) => {
                      setParseSuccess(
                        res.addedLines === 0
                          ? "No transactions were extracted from this document."
                          : `Imported ${res.addedLines} statement line${res.addedLines === 1 ? "" : "s"}.`,
                      );
                      setPdfFile(null);
                      if (fileInputRef.current) {
                        fileInputRef.current.value = "";
                      }
                    },
                  },
                );
              }}
            >
              {parseStatement.isPending ? "Parsing…" : "Upload & parse"}
            </button>
            <button
              type="button"
              className="btn btn-outline-secondary btn-sm"
              disabled={parseStatement.isPending}
              onClick={() => {
                setPdfFile(null);
                setParseSuccess(null);
                setImportMortgageOnly(false);
                if (fileInputRef.current) {
                  fileInputRef.current.value = "";
                }
              }}
            >
              Clear
            </button>
          </>
        }
      >
        <div className="row g-2 align-items-end">
          <div className="col-md-8">
            <label
              className="form-label small mb-0"
              htmlFor={`${houseKey}-statement-pdf`}
            >
              {importFileLabel}
            </label>
            <input
              id={`${houseKey}-statement-pdf`}
              ref={fileInputRef}
              type="file"
              accept="application/pdf,image/*"
              className="form-control form-control-sm"
              disabled={parseStatement.isPending}
              onChange={(ev) => {
                const next = ev.target.files?.[0] ?? null;
                setPdfFile(next);
                setParseSuccess(null);
              }}
            />
          </div>
        </div>
        {showMortgageImport ? (
        <div className="form-check mt-2">
          <input
            id={`${houseKey}-statement-import-mortgage-only`}
            className="form-check-input"
            type="checkbox"
            checked={importMortgageOnly}
            disabled={parseStatement.isPending}
            onChange={(ev) => setImportMortgageOnly(ev.target.checked)}
          />
          <label
            className="form-check-label small"
            htmlFor={`${houseKey}-statement-import-mortgage-only`}
          >
            Mortgage
          </label>
          <p className="form-text small mb-0 mt-1">
            When checked, only lines classified as Mortgage are imported; all other
            extracted transactions are discarded.
          </p>
        </div>
        ) : null}
        {parseStatement.isPending ? (
          <p className="small text-muted mt-2 mb-0">
            Uploading and parsing — often under a minute; large or scanned PDFs can take several minutes.
          </p>
        ) : null}
        {parseStatement.isError ? (
          <div
            className="alert alert-danger py-2 small mt-3 mb-0"
            role="alert"
          >
            {parseStatement.error?.message ?? "Statement import failed."}
          </div>
        ) : null}
        {parseSuccess && !parseStatement.isPending ? (
          <div
            className="alert alert-success py-2 small mt-3 mb-0"
            role="status"
          >
            {parseSuccess}
          </div>
        ) : null}
            </AdminEditorSection>
          </AdminDisclosure>
        }
      >
        <AdminDataTable bare columns={TABLE_COLUMNS}>
          {expanded.expandedId === DRAFT_RECORD_ID ? (
            <AdminExpandableRow
              colSpan={COL_SPAN}
              expanded
              onToggle={openCreate}
              editor={lineEditor}
            >
              <AdminCell column="when" className="small">New</AdminCell>
              <AdminCell column="type" className="small">—</AdminCell>
              <AdminCell column="desc" className="small">New line</AdminCell>
              <AdminCell column="net" />
              <AdminCell column="vat" />
              <AdminCell column="ccy" />
              <AdminCell column="gross" />
              <AdminCell column="ops" />
            </AdminExpandableRow>
          ) : null}
          {filteredLines.length ? (
            filteredLines.map((line) => (
              <AdminExpandableRow
                key={line.id}
                colSpan={COL_SPAN}
                expanded={expanded.expandedId === line.id}
                onToggle={() => openEdit(line)}
                editor={lineEditor}
              >
                <AdminCell column="when" className="small">
                  {formatDateUtc(line.dateUtc)}
                </AdminCell>
                <AdminCell column="type" className="small">
                  <span className={statementLineTypeClass(line.type)}>
                    {statementLineTypeLabel(line.type, lockedLineType)}
                  </span>
                </AdminCell>
                <AdminCell column="desc" className="small">
                  <div className="d-flex flex-wrap align-items-center gap-2">
                    <span>{line.description}</span>
                    {statementLineAssetKeys(line).map((assetKey) => (
                      <span
                        key={assetKey}
                        className="d-inline-flex flex-wrap align-items-center gap-2"
                      >
                        <StatementAssetLaunchButton
                          assetKey={assetKey}
                          openingPdfKey={openingPdfKey}
                          onOpen={openStatementPdf}
                        />
                        <span className="text-muted small text-break">
                          {basenameFromAssetKey(assetKey)}
                        </span>
                      </span>
                    ))}
                  </div>
                  <AdminDataTableCellMeta>
                    {formatDateUtc(line.dateUtc)}
                    {" · "}
                    <span className={statementLineTypeClass(line.type)}>
                      {statementLineTypeLabel(line.type, lockedLineType)}
                    </span>
                    {" · "}
                    {line.currency}
                  </AdminDataTableCellMeta>
                </AdminCell>
                <AdminCell column="net" className="small text-end">
                  <MoneyAmount
                    amount={line.netAmount}
                    currency={line.currency}
                    amountOnly
                  />
                </AdminCell>
                <AdminCell column="vat" className="small text-end">
                  <MoneyAmount
                    amount={line.vat}
                    currency={line.currency}
                    amountOnly
                  />
                </AdminCell>
                <AdminCell column="ccy" className="small">{line.currency}</AdminCell>
                <AdminCell column="gross" className="small text-end">
                  <MoneyAmount
                    amount={line.grossAmount}
                    currency={line.currency}
                    amountOnly
                  />
                </AdminCell>
                <AdminCell column="ops" className="small text-end">
                  <AdminRowActions
                    actions={[
                      {
                        id: "edit",
                        label: "Edit line",
                        iconClassName: "bi bi-pencil",
                        onClick: () => openEdit(line),
                      },
                      {
                        id: "duplicate",
                        label: "Duplicate line",
                        iconClassName: "bi bi-copy",
                        onClick: () => openDuplicateIntoEditor(line),
                      },
                      {
                        id: "delete",
                        label: "Delete line",
                        iconClassName: "bi bi-trash",
                        danger: true,
                        onClick: () => setPendingDeleteId(line.id),
                      },
                    ]}
                  />
                </AdminCell>
              </AdminExpandableRow>
            ))
          ) : (
            <AdminDataTableEmptyRow
              colSpan={COL_SPAN}
              message={
                sortedLines.length ? "No lines match the filter." : emptyMessage
              }
            />
          )}
        </AdminDataTable>
        <ConfirmDialog
          open={pendingDeleteId !== null}
          title="Delete line"
          body="Delete this statement line?"
          confirmLabel="Delete"
          tone="danger"
          onConfirm={() => {
            if (pendingDeleteId) deleteLine(pendingDeleteId);
          }}
          onCancel={() => setPendingDeleteId(null)}
        />
        <ConfirmDialog
          open={expanded.confirmOpen}
          title="Discard unsaved edits?"
          body="This line has unsaved changes."
          confirmLabel="Discard"
          cancelLabel="Keep editing"
          tone="danger"
          onConfirm={expanded.acceptPending}
          onCancel={expanded.cancelPending}
        />
      </AdminRecordTable>
    </div>
  );
}
