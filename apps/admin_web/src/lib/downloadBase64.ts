const REVOKE_MS = 60_000;

function decoded(dataBase64: string): Uint8Array {
  const binary = atob(dataBase64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

function blob(contentType: string, dataBase64: string): Blob {
  const bytes = decoded(dataBase64);
  const copy = new ArrayBuffer(bytes.byteLength);
  new Uint8Array(copy).set(bytes);
  return new Blob([copy], { type: contentType });
}

export function downloadBase64(filename: string, contentType: string, dataBase64: string): void {
  const url = URL.createObjectURL(blob(contentType, dataBase64));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), REVOKE_MS);
}

/** Open the preview window in the click handler, before any await. */
export function openPreview(): Window | null {
  const popup = window.open("about:blank", "_blank");
  if (popup) popup.opener = null;
  return popup;
}

export function showPreview(popup: Window | null, filename: string, contentType: string, dataBase64: string): void {
  if (!popup || popup.closed) {
    downloadBase64(filename, contentType, dataBase64);
    return;
  }
  const url = URL.createObjectURL(blob(contentType, dataBase64));
  popup.location.href = url;
  window.setTimeout(() => URL.revokeObjectURL(url), REVOKE_MS);
}
