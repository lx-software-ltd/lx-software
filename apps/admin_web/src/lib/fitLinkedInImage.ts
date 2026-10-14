import { IMAGE_BYTE_MAX, IMAGE_SOURCE_BYTE_MAX } from "./linkedinModel";

export type LinkedInImageUpload = {
  contentType: "image/png" | "image/jpeg";
  dataBase64: string;
};

export type JpegFrame = {
  width: number;
  height: number;
  encode: (width: number, height: number, quality: number) => Promise<Blob>;
};

type CanvasPainter = Pick<CanvasRenderingContext2D, "fillStyle" | "fillRect" | "drawImage">;
type UploadKind = "image/png" | "image/jpeg" | "image/heic";

const MAX_EDGE = 1600;
const MIN_EDGE = 320;
const CANVAS_EDGE_MAX = 4096;
const START_QUALITY = 0.85;
const MIN_QUALITY = 0.7;
const TO_BLOB_TIMEOUT_MS = 1500;

export function linkedInUploadType(file: File): UploadKind | null {
  const type = file.type.toLowerCase().split(";")[0]?.trim() ?? "";
  if (type === "image/png") return "image/png";
  if (type === "image/jpeg" || type === "image/jpg" || type === "image/pjpeg") return "image/jpeg";
  if (type === "image/heic" || type === "image/heif") return "image/heic";
  if (type === "" || type === "application/octet-stream") return kindFromName(file.name);
  return null;
}

export async function fitLinkedInImage(
  file: File,
  shrink: (file: File) => Promise<LinkedInImageUpload> = shrinkLinkedInImage,
): Promise<LinkedInImageUpload> {
  const kind = linkedInUploadType(file);
  if (kind !== "image/png" && kind !== "image/jpeg" && kind !== "image/heic") {
    throw new Error("Use a PNG or JPEG image.");
  }
  if (!file.size) {
    throw new Error("The image is empty.");
  }
  if (file.size > IMAGE_SOURCE_BYTE_MAX) {
    throw new Error("That photo is too large to resize here. Use a file under 25 MB.");
  }
  if (kind !== "image/heic" && file.size <= IMAGE_BYTE_MAX) {
    return { contentType: kind, dataBase64: await readFileAsBase64(file) };
  }
  return shrink(file);
}

export function scaleToMaxEdge(
  width: number,
  height: number,
  maxEdge = MAX_EDGE,
): { width: number; height: number } {
  const edge = Math.max(width, height);
  if (edge <= maxEdge) {
    return { width, height };
  }
  const scale = maxEdge / edge;
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}

/**
 * Intermediate sizes before the final frame. Safari blanks a canvas when one
 * draw shrinks a camera original by more than half, or past 4096px.
 */
export function downsampleSteps(
  sourceWidth: number,
  sourceHeight: number,
  targetWidth: number,
  targetHeight: number,
): { width: number; height: number }[] {
  const steps: { width: number; height: number }[] = [];
  let width = sourceWidth;
  let height = sourceHeight;
  for (let index = 0; index < 12; index += 1) {
    const overScale = width > targetWidth * 2 || height > targetHeight * 2;
    const overCanvas = width > CANVAS_EDGE_MAX || height > CANVAS_EDGE_MAX;
    if (!overScale && !overCanvas) break;
    let nextWidth = Math.max(targetWidth, Math.floor(width / 2));
    let nextHeight = Math.max(targetHeight, Math.floor(height / 2));
    if (nextWidth > CANVAS_EDGE_MAX || nextHeight > CANVAS_EDGE_MAX) {
      const capped = scaleToMaxEdge(nextWidth, nextHeight, CANVAS_EDGE_MAX);
      nextWidth = Math.max(targetWidth, capped.width);
      nextHeight = Math.max(targetHeight, capped.height);
    }
    if (nextWidth === width && nextHeight === height) break;
    steps.push({ width: nextWidth, height: nextHeight });
    width = nextWidth;
    height = nextHeight;
  }
  return steps;
}

export function nextEncodeStep(
  width: number,
  height: number,
  quality: number,
): { width: number; height: number; quality: number } | null {
  const widthNext = Math.floor(width * 0.85);
  const heightNext = Math.floor(height * 0.85);
  if (widthNext >= MIN_EDGE && heightNext >= MIN_EDGE) {
    return { width: widthNext, height: heightNext, quality };
  }
  const qualityNext = Math.round((quality - 0.05) * 100) / 100;
  if (qualityNext < MIN_QUALITY) return null;
  return { width, height, quality: qualityNext };
}

/** JPEG has no alpha. White is the matte so a transparent PNG does not turn black. */
export function paintLinkedInFrame(
  context: CanvasPainter,
  image: CanvasImageSource,
  width: number,
  height: number,
): void {
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, width, height);
  context.drawImage(image, 0, 0, width, height);
}

/** Safari on iPad often calls `toBlob` with null for a photo that did draw. */
export function jpegBlobFromCanvas(canvas: HTMLCanvasElement, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const fail = () => {
      if (settled) return;
      settled = true;
      reject(new Error("The picture could not be read."));
    };
    const succeed = (blob: Blob) => {
      if (settled) return;
      settled = true;
      resolve(blob);
    };
    const fromDataUrl = () => {
      try {
        const blob = dataUrlToBlob(canvas.toDataURL("image/jpeg", quality));
        if (!blob.size) {
          fail();
          return;
        }
        succeed(blob);
      } catch {
        fail();
      }
    };
    const timer = setTimeout(fromDataUrl, TO_BLOB_TIMEOUT_MS);
    try {
      canvas.toBlob(
        (blob) => {
          clearTimeout(timer);
          if (blob && blob.size > 0) succeed(blob);
          else fromDataUrl();
        },
        "image/jpeg",
        quality,
      );
    } catch {
      clearTimeout(timer);
      fromDataUrl();
    }
  });
}

export async function shrinkLinkedInImage(file: File, frame?: JpegFrame): Promise<LinkedInImageUpload> {
  const opened = frame ? null : await openDecodable(file);
  const source: JpegFrame = frame ?? opened!.frame;
  try {
    let { width, height } = scaleToMaxEdge(source.width, source.height);
    let quality = START_QUALITY;
    for (;;) {
      const blob = await source.encode(width, height, quality);
      if (blob.size <= IMAGE_BYTE_MAX) {
        return { contentType: "image/jpeg", dataBase64: await blobToBase64(blob) };
      }
      const next = nextEncodeStep(width, height, quality);
      if (!next) {
        throw new Error("The image must be under 1.5 MB.");
      }
      width = next.width;
      height = next.height;
      quality = next.quality;
    }
  } finally {
    opened?.release();
  }
}

function kindFromName(name: string): UploadKind | null {
  const lower = name.toLowerCase();
  if (lower.endsWith(".png")) return "image/png";
  if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image/jpeg";
  if (lower.endsWith(".heic") || lower.endsWith(".heif")) return "image/heic";
  return null;
}

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const encoded = String(reader.result ?? "").split(",")[1] ?? "";
      if (!encoded) {
        reject(new Error("The image could not be read."));
        return;
      }
      resolve(encoded);
    };
    reader.onerror = () => reject(new Error("The image could not be read."));
    reader.readAsDataURL(file);
  });
}

async function openDecodable(file: File): Promise<{ frame: JpegFrame; release: () => void }> {
  const kind = linkedInUploadType(file) ?? "image/jpeg";
  const blob = new Blob([await file.arrayBuffer()], { type: kind });
  const bitmap = await tryBitmap(blob);
  if (bitmap) return bitmapFrame(bitmap);
  return imageFrame(blob);
}

async function tryBitmap(blob: Blob): Promise<ImageBitmap | null> {
  if (typeof createImageBitmap !== "function") return null;
  const attempts: Array<ImageBitmapOptions | undefined> = [
    { resizeWidth: MAX_EDGE, resizeQuality: "high" },
    undefined,
  ];
  for (const options of attempts) {
    try {
      const bitmap = options ? await createImageBitmap(blob, options) : await createImageBitmap(blob);
      if (bitmap.width > 0 && bitmap.height > 0) return bitmap;
      bitmap.close();
    } catch {
      // Resize options are unsupported, or this blob is not a bitmap here.
    }
  }
  return null;
}

function bitmapFrame(bitmap: ImageBitmap): { frame: JpegFrame; release: () => void } {
  let closed = false;
  return {
    frame: {
      width: bitmap.width,
      height: bitmap.height,
      encode: (width, height, quality) => encodeSource(bitmap, bitmap.width, bitmap.height, width, height, quality),
    },
    release: () => {
      if (closed) return;
      closed = true;
      bitmap.close();
    },
  };
}

async function imageFrame(blob: Blob): Promise<{ frame: JpegFrame; release: () => void }> {
  const opened = await openImage(blob);
  const width = opened.image.naturalWidth || opened.image.width;
  const height = opened.image.naturalHeight || opened.image.height;
  if (!width || !height) {
    opened.release();
    throw new Error("The picture could not be read.");
  }
  return {
    frame: {
      width,
      height,
      encode: (targetWidth, targetHeight, quality) =>
        encodeSource(opened.image, width, height, targetWidth, targetHeight, quality),
    },
    release: opened.release,
  };
}

async function openImage(blob: Blob): Promise<{ image: HTMLImageElement; release: () => void }> {
  const url = URL.createObjectURL(blob);
  let released = false;
  const release = () => {
    if (released) return;
    released = true;
    URL.revokeObjectURL(url);
  };
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error("The picture could not be read."));
      img.src = url;
    });
    return { image, release };
  } catch (error) {
    release();
    throw error;
  }
}

async function encodeSource(
  image: CanvasImageSource,
  sourceWidth: number,
  sourceHeight: number,
  width: number,
  height: number,
  quality: number,
): Promise<Blob> {
  let current = image;
  for (const step of downsampleSteps(sourceWidth, sourceHeight, width, height)) {
    current = drawToCanvas(current, step.width, step.height);
  }
  return jpegBlobFromCanvas(drawToCanvas(current, width, height), quality);
}

function drawToCanvas(image: CanvasImageSource, width: number, height: number): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("The picture could not be read.");
  }
  paintLinkedInFrame(context, image, width, height);
  return canvas;
}

function dataUrlToBlob(url: string): Blob {
  const comma = url.indexOf(",");
  if (comma < 0) return new Blob();
  const meta = url.slice(0, comma);
  const payload = url.slice(comma + 1);
  if (!payload || !meta.startsWith("data:")) return new Blob();
  const mime = /data:([^;,]+)/.exec(meta)?.[1] || "image/jpeg";
  const binary = atob(payload);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return new Blob([bytes], { type: mime });
}

async function blobToBase64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
  }
  return btoa(binary);
}
