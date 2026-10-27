import { useRef, useState } from "react";
import type { FinanceLineType, HouseFinanceData, StatementOwnerKey } from "../lib/financeModel";
import {
  existingImportedStatementBasenames,
  statementImportResultMessage,
  type StatementImportNotice,
  useParseStatement,
} from "../hooks/useParseStatement";
import { AdminDisclosure, AdminEditorSection, ConfirmDialog } from "./ui";

export type StatementImportControlProps = {
  readonly owner: StatementOwnerKey;
  readonly data: HouseFinanceData;
  readonly lockedLineType?: Extract<FinanceLineType, "income" | "expenditure">;
  readonly showMortgageImport?: boolean;
  readonly title: string;
  readonly description: string;
  readonly fileLabel: string;
};

/**
 * Upload a statement and parse it. A filename already on a line asks first.
 * Inbound mail does not use this control; it parses a new S3 key directly.
 */
export function StatementImportControl({
  owner,
  data,
  lockedLineType,
  showMortgageImport = true,
  title,
  description,
  fileLabel,
}: StatementImportControlProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [importMortgageOnly, setImportMortgageOnly] = useState(false);
  const [parseNotice, setParseNotice] = useState<StatementImportNotice | null>(null);
  const [repeatOpen, setRepeatOpen] = useState(false);
  const parseStatement = useParseStatement(owner);

  function clearFile() {
    setPdfFile(null);
    setParseNotice(null);
    setImportMortgageOnly(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function startParse(file: File) {
    setParseNotice(null);
    setRepeatOpen(false);
    parseStatement.mutate(
      {
        file,
        mortgageOnly: showMortgageImport && importMortgageOnly,
        ...(lockedLineType ? { lineTypeOnly: lockedLineType } : {}),
      },
      {
        onSuccess: (res) => {
          setParseNotice(statementImportResultMessage(res));
          setPdfFile(null);
          if (fileInputRef.current) fileInputRef.current.value = "";
        },
      },
    );
  }

  function requestParse() {
    if (!pdfFile || parseStatement.isPending) return;
    const basenames = existingImportedStatementBasenames(data);
    if (basenames.has(pdfFile.name)) {
      setRepeatOpen(true);
      return;
    }
    startParse(pdfFile);
  }

  return (
    <>
      <AdminDisclosure title={title} presentation="dialog">
        <p className="small text-muted">{description}</p>
        <AdminEditorSection
          embedded
          footer={
            <>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                disabled={!pdfFile || parseStatement.isPending}
                onClick={requestParse}
              >
                {parseStatement.isPending ? "Parsing…" : "Upload & parse"}
              </button>
              <button
                type="button"
                className="btn btn-outline-secondary btn-sm"
                disabled={parseStatement.isPending}
                onClick={clearFile}
              >
                Clear
              </button>
            </>
          }
        >
          <div className="row g-2 align-items-end">
            <div className="col-md-8">
              <label className="form-label small mb-0" htmlFor={`${owner}-statement-pdf`}>
                {fileLabel}
              </label>
              <input
                id={`${owner}-statement-pdf`}
                ref={fileInputRef}
                type="file"
                accept="application/pdf,image/*"
                className="form-control form-control-sm"
                disabled={parseStatement.isPending}
                onChange={(ev) => {
                  setPdfFile(ev.target.files?.[0] ?? null);
                  setParseNotice(null);
                }}
              />
            </div>
          </div>
          {showMortgageImport ? (
            <div className="form-check mt-2">
              <input
                id={`${owner}-statement-import-mortgage-only`}
                className="form-check-input"
                type="checkbox"
                checked={importMortgageOnly}
                disabled={parseStatement.isPending}
                onChange={(ev) => setImportMortgageOnly(ev.target.checked)}
              />
              <label className="form-check-label small" htmlFor={`${owner}-statement-import-mortgage-only`}>
                Mortgage
              </label>
              <p className="form-text small mb-0 mt-1">
                When checked, only lines classified as Mortgage are imported; all other extracted transactions are
                discarded.
              </p>
            </div>
          ) : null}
          {parseStatement.isPending ? (
            <p className="small text-muted mt-2 mb-0">
              Uploading and parsing — often under a minute; large or scanned PDFs can take several minutes.
            </p>
          ) : null}
          {parseStatement.isError ? (
            <div className="alert alert-danger py-2 small mt-3 mb-0" role="alert">
              {parseStatement.error?.message ?? "Statement import failed."}
            </div>
          ) : null}
          {parseNotice && !parseStatement.isPending ? (
            <div
              className={`alert ${parseNotice.tone === "warning" ? "alert-warning" : "alert-success"} py-2 small mt-3 mb-0`}
              role="status"
            >
              {parseNotice.text}
            </div>
          ) : null}
        </AdminEditorSection>
      </AdminDisclosure>
      <ConfirmDialog
        open={repeatOpen}
        title="Parse this file again?"
        body={
          pdfFile
            ? `A statement file named "${pdfFile.name}" was already imported. Parsing it again adds its lines a second time.`
            : "This filename was already imported. Parsing it again adds its lines a second time."
        }
        confirmLabel="Parse anyway"
        cancelLabel="Cancel"
        onConfirm={() => {
          if (pdfFile) startParse(pdfFile);
        }}
        onCancel={() => setRepeatOpen(false)}
      />
    </>
  );
}
