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
  const file = blob(contentType, dataBase64);
  const url = URL.createObjectURL(file);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function openBase64(contentType: string, dataBase64: string): void {
  const url = URL.createObjectURL(blob(contentType, dataBase64));
  window.open(url, "_blank", "noopener");
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
