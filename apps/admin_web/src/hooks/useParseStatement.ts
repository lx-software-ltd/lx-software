import { useMutation, useQueryClient } from "@tanstack/react-query";
import { adminFetchJson, getAdminApiErrorMessage } from "../lib/apiAdminClient";
import { log } from "../lib/log";
import {
  statementLineAssetKeys,
  type FinanceLineType,
  type FinancePersistedState,
  type HouseFinanceData,
  type StatementOwnerKey,
} from "../lib/financeModel";
import {
  isHouseKey,
  parseStatementJobPath,
  parseStatementStartPath,
  statementOwnerQueryKey,
} from "../lib/statementOwners";
import { uploadFinanceAsset } from "../lib/uploadFinanceAsset";

const DUPLICATE_STATEMENT_BASE_MSG =
  "Remove its imported lines or rename the file, then try again.";

import {
  PARSE_POLL_BACKOFF_CAP_MS,
  PARSE_POLL_DEADLINE_MS,
  PARSE_POLL_INITIAL_WAIT_MS,
} from "../lib/contracts/generated";

/**
 * Collects exact filenames (S3 key basenames) already used by lines with
 * statement attachments. When `excludeLineId` is set, that line is ignored (e.g.
 * while editing the same record).
 */
export function existingImportedStatementBasenames(
  data: HouseFinanceData,
  excludeLineId?: string,
): ReadonlySet<string> {
  const out = new Set<string>();
  for (const line of data.lines) {
    if (excludeLineId && line.id === excludeLineId) continue;
    for (const key of statementLineAssetKeys(line)) {
      const parts = key.split("/");
      const base = parts[parts.length - 1];
      if (base) out.add(base);
    }
  }
  return out;
}

type ParseJobStartResponse = {
  readonly jobId: string;
  readonly status?: string;
};

type ParseJobPollResponse =
  | { readonly status: "pending" | "processing" }
  | {
      readonly status: "succeeded";
      readonly addedLines: number;
      readonly sourceAssetKeys?: readonly string[];
      readonly sourceAssetKey?: string;
    }
  | { readonly status: "failed"; readonly message?: string };

export type ParseStatementResult = {
  readonly addedLines: number;
  readonly sourceAssetKeys: readonly string[];
};

export type ParseStatementVariables = {
  readonly file: File;
  readonly mortgageOnly?: boolean;
  readonly lineTypeOnly?: Extract<FinanceLineType, "income" | "expenditure">;
};

/**
 * Re-exported from `uploadFinanceAsset` for backward compatibility with tests
 * and call sites that imported it from this module.
 */
export { extractS3ErrorCode } from "../lib/uploadFinanceAsset";

function bookDataForOwner(
  owner: StatementOwnerKey,
  qc: ReturnType<typeof useQueryClient>,
): HouseFinanceData | undefined {
  if (isHouseKey(owner)) {
    return qc.getQueryData<FinancePersistedState>(["finance"])?.[owner];
  }
  return qc.getQueryData<HouseFinanceData>(statementOwnerQueryKey(owner));
}

async function pollParseJob(
  owner: StatementOwnerKey,
  jobId: string,
): Promise<ParseStatementResult> {
  const deadline = Date.now() + PARSE_POLL_DEADLINE_MS;
  let nextWaitMs = PARSE_POLL_INITIAL_WAIT_MS;
  while (Date.now() < deadline) {
    const j = await adminFetchJson<ParseJobPollResponse>(
      parseStatementJobPath(owner, jobId),
    );
    if (j.status === "succeeded") {
      const keys =
        Array.isArray(j.sourceAssetKeys) && j.sourceAssetKeys.length > 0
          ? [...j.sourceAssetKeys]
          : j.sourceAssetKey
            ? [j.sourceAssetKey]
            : [];
      return {
        addedLines: j.addedLines,
        sourceAssetKeys: keys,
      };
    }
    if (j.status === "failed") {
      throw new Error(j.message?.trim() || "Statement import failed.");
    }
    await new Promise((r) => setTimeout(r, nextWaitMs));
    nextWaitMs = Math.min(PARSE_POLL_BACKOFF_CAP_MS, nextWaitMs * 2);
  }
  throw new Error(
    "Statement parse is taking longer than expected. Reload the page and check whether new lines appeared.",
  );
}

/**
 * Upload a PDF (or supported image) statement to S3 then call the admin API
 * to extract statement lines via OpenRouter and append them to the owner's
 * finance record. Parsing runs asynchronously on the server (avoids API
 * Gateway timeouts); this hook polls until the job completes then refreshes
 * cached book data.
 *
 * Pass `{ mortgageOnly: true }` to append only parser rows with type `mortgage`.
 * Pass `{ lineTypeOnly: "expenditure" | "income" }` for tab-scoped imports.
 */
export function useParseStatement(owner: StatementOwnerKey) {
  const qc = useQueryClient();
  return useMutation<ParseStatementResult, Error, ParseStatementVariables>({
    mutationFn: async ({ file, mortgageOnly = false, lineTypeOnly }) => {
      if (!file) {
        throw new Error("No file selected");
      }
      const lowered = file.name.toLowerCase();
      const contentType =
        file.type ||
        (lowered.endsWith(".pdf")
          ? "application/pdf"
          : lowered.endsWith(".png")
            ? "image/png"
            : lowered.endsWith(".jpg") || lowered.endsWith(".jpeg")
              ? "image/jpeg"
              : "");
      if (!contentType.startsWith("image/") && contentType !== "application/pdf") {
        throw new Error("Only PDF or image statements are supported.");
      }

      const book = bookDataForOwner(owner, qc);
      if (book) {
        const basenames = existingImportedStatementBasenames(book);
        if (basenames.has(file.name)) {
          throw new Error(
            `A statement file named "${file.name}" was already imported. ${DUPLICATE_STATEMENT_BASE_MSG}`,
          );
        }
      }

      log.info("[useParseStatement] start", {
        owner,
        fileName: file.name,
        fileType: file.type,
        contentTypeRequested: contentType,
        fileSize: file.size,
        mortgageOnly,
        lineTypeOnly,
      });

      const uploadKey = await uploadFinanceAsset(file, owner, qc);
      log.info("[useParseStatement] upload + confirm ok", {
        key: uploadKey,
        size: file.size,
      });

      let jobStart: ParseJobStartResponse;
      try {
        jobStart = await adminFetchJson<ParseJobStartResponse>(
          parseStatementStartPath(owner),
          {
            method: "POST",
            body: JSON.stringify({
              key: uploadKey,
              ...(mortgageOnly ? { mortgageOnly: true } : {}),
              ...(lineTypeOnly ? { lineTypeOnly } : {}),
            }),
          },
        );
      } catch (err) {
        const apiMsg = getAdminApiErrorMessage(err);
        if (apiMsg) throw new Error(apiMsg);
        throw err;
      }
      if (!jobStart.jobId?.trim()) {
        throw new Error("Statement parse did not return a job id.");
      }

      const result = await pollParseJob(owner, jobStart.jobId.trim());
      await qc.invalidateQueries({ queryKey: [...statementOwnerQueryKey(owner)] });

      log.info("[useParseStatement] parse job ok", {
        key: uploadKey,
        addedLines: result.addedLines,
      });

      return result;
    },
  });
}
