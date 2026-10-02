import type { QueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "./apiAdminClient";
import { log } from "./log";
import { keys } from "./queryKeys";
import type { StatementOwnerKey } from "./financeModel";

type PresignedUpload = {
  readonly url: string;
  readonly fields: Record<string, string>;
};

type UploadUrlResponse = {
  readonly upload: PresignedUpload;
  readonly key: string;
};

type ConfirmAssetResponse = {
  readonly item: { readonly pk: string };
};

/**
 * Pull the `<Code>…</Code>` value out of an S3 error XML body so we can
 * surface a short, actionable message in the UI (e.g. `EntityTooLarge`,
 * `AccessDenied`, `MalformedPOSTRequest`) instead of an XML wall.
 *
 * Exported for tests.
 */
export function extractS3ErrorCode(body: string): string | null {
  if (!body) return null;
  const m = /<Code>\s*([^<\s][^<]*?)\s*<\/Code>/i.exec(body);
  return m ? m[1].trim() : null;
}

async function sha256Hex(file: File): Promise<string | undefined> {
  if (typeof crypto === "undefined" || !crypto.subtle) {
    return undefined;
  }
  try {
    const buf = await file.arrayBuffer();
    const digest = await crypto.subtle.digest("SHA-256", buf);
    return Array.from(new Uint8Array(digest))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  } catch {
    return undefined;
  }
}

async function uploadToS3(presigned: PresignedUpload, file: File): Promise<void> {
  const form = new FormData();
  for (const [k, v] of Object.entries(presigned.fields)) {
    form.append(k, v);
  }
  form.append("file", file);

  const contentTypeField = presigned.fields["Content-Type"];
  const keyField = presigned.fields.key;
  log.info("[uploadFinanceAsset] uploading to S3", {
    url: presigned.url,
    key: keyField,
    contentTypeField,
    fileType: file.type,
    fileSize: file.size,
    fileName: file.name,
  });

  let res: Response;
  try {
    res = await fetch(presigned.url, { method: "POST", body: form });
  } catch (err) {
    log.error("[uploadFinanceAsset] S3 POST transport failure", err);
    const reason = err instanceof Error ? err.message : String(err);
    throw new Error(
      `S3 upload network/CORS failure (no HTTP response): ${reason}`,
    );
  }

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    const code = extractS3ErrorCode(text);
    const summary = code ? `${code}` : text.slice(0, 200) || "no body";
    log.error("[uploadFinanceAsset] S3 POST rejected", {
      status: res.status,
      code,
      bodyPreview: text.slice(0, 1000),
      contentTypeField,
      keyField,
    });
    throw new Error(`S3 upload failed (${res.status}): ${summary}`);
  }
  log.info("[uploadFinanceAsset] S3 upload OK", { status: res.status });
}

/**
 * Upload a finance asset (PDF or statement image) to S3, confirm metadata in DynamoDB,
 * Returns the S3 object key so callers can append it to a statement line's `sourceAssetKeys`.
 */
export async function uploadFinanceAsset(
  file: File,
  house: StatementOwnerKey,
  queryClient: QueryClient,
): Promise<string> {
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
    throw new Error("Only PDF or image files are supported.");
  }

  const upload = await adminFetchJson<UploadUrlResponse>(
    "/assets/upload-url",
    {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        contentType,
      }),
    },
  );

  await uploadToS3(upload.upload, file);

  const sha256 = await sha256Hex(file);
  await adminFetchJson<ConfirmAssetResponse>("/assets/confirm", {
    method: "POST",
    body: JSON.stringify({
      key: upload.key,
      house,
      size: file.size,
      ...(sha256 ? { sha256 } : {}),
    }),
  });

  void queryClient.invalidateQueries({ queryKey: [...keys.admin, "asset-records"] });

  return upload.key;
}
