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

type CanvasPainter = {
  fillStyle: string;
  fillRect: (x: number, y: number, width: number, height: number) => void;
  drawImage: (image: CanvasImageSource, dx: number, dy: number, dw: number, dh: number) => void;
};

const MAX_EDGE = 1600;
const MIN_EDGE = 320;
const START_QUALITY = 0.85;
const MIN_QUALITY = 0.7;

export async function fitLinkedInImage(
  file: File,
  shrink: (file: File) => Promise<LinkedInImageUpload> = shrinkLinkedInImage,
): Promise<LinkedInImageUpload> {
  if (file.type !== "image/png" && file.type !== "image/jpeg") {
    throw new Error("Use a PNG or JPEG image.");
  }
  if (!file.size) {
    throw new Error("The image is empty.");
  }
  if (file.size > IMAGE_SOURCE_BYTE_MAX) {
    throw new Error("That photo is too large to resize here. Use a file under 25 MB.");
  }
  if (file.size <= IMAGE_BYTE_MAX) {
    return { contentType: file.type, dataBase64: await readFileAsBase64(file) };
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

export async function shrinkLinkedInImage(file: File, frame?: JpegFrame): Promise<LinkedInImageUpload> {
  const opened = frame ? null : await openImage(file);
  const source: JpegFrame = frame ?? {
    width: opened!.image.naturalWidth || opened!.image.width,
    height: opened!.image.naturalHeight || opened!.image.height,
    encode: (width, height, quality) => encodeJpeg(opened!.image, width, height, quality),
  };
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

async function openImage(file: File): Promise<{ image: HTMLImageElement; release: () => void }> {
  const url = URL.createObjectURL(file);
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

function encodeJpeg(
  image: CanvasImageSource,
  width: number,
  height: number,
  quality: number,
): Promise<Blob> {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) {
    return Promise.reject(new Error("The picture could not be read."));
  }
  paintLinkedInFrame(context, image, width, height);
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("The picture could not be read."))),
      "image/jpeg",
      quality,
    );
  });
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
