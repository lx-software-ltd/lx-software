import {
  VIDEO_BYTE_MAX,
  VIDEO_BYTE_MIN,
  VIDEO_DURATION_MAX_SECONDS,
  VIDEO_DURATION_MIN_SECONDS,
  VIDEO_PASS_MAX_SECONDS,
  VIDEO_SOURCE_BYTE_MAX,
} from "./linkedinModel";

export type LinkedInVideoUpload = {
  contentType: "video/mp4";
  dataBase64: string;
};

export type VideoPrepare = {
  durationSeconds?: (file: File) => Promise<number>;
  transcode?: (file: File) => Promise<Blob>;
};

type Playback = {
  video: HTMLVideoElement;
  release: () => void;
};

const H264_BRANDS = new Set(["isom", "iso2", "mp41", "mp42", "avc1", "M4V "]);
const PREPARE_ERROR = "This browser cannot prepare that video. Export an MP4 under 3 MB.";

export function mp4MajorBrand(bytes: Uint8Array): string | null {
  if (bytes.length < 12) return null;
  if (ascii(bytes, 4, 8) !== "ftyp") return null;
  return ascii(bytes, 8, 12);
}

/** True when the file is already an MP4 brand LinkedIn can play. QuickTime and HEVC are not. */
export function isPassThroughMp4(bytes: Uint8Array): boolean {
  const brand = mp4MajorBrand(bytes);
  return brand !== null && H264_BRANDS.has(brand);
}

/** Bits per second that lands near the stored cap for this duration. */
export function videoBitsPerSecond(durationSeconds: number, byteMax = VIDEO_BYTE_MAX): number {
  const bits = Math.floor((byteMax * 0.85 * 8) / Math.max(durationSeconds, 0.1));
  return Math.min(1_200_000, Math.max(250_000, bits));
}

export function mp4RecorderMime(): string | null {
  if (typeof MediaRecorder === "undefined") return null;
  if (typeof MediaRecorder.isTypeSupported !== "function") return "video/mp4";
  return MediaRecorder.isTypeSupported("video/mp4") ? "video/mp4" : null;
}

/**
 * Store an H.264 MP4 that already fits, or re-encode a camera clip.
 * Playback starts before the first await so an iPad gesture can begin the video.
 */
export async function prepareLinkedInVideo(file: File, options?: VideoPrepare): Promise<LinkedInVideoUpload> {
  if (!file.size) throw new Error("The video is empty.");
  if (file.size > VIDEO_SOURCE_BYTE_MAX) {
    throw new Error("That video is too large to prepare here. Use a file under 80 MB.");
  }
  const playback = options?.durationSeconds ? null : startVideoPlayback(file);
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    const duration = options?.durationSeconds ? await options.durationSeconds(file) : await readDuration(playback);
    if (!Number.isFinite(duration) || duration < VIDEO_DURATION_MIN_SECONDS) {
      throw new Error("LinkedIn needs a video of at least 3 seconds.");
    }
    if (file.size >= VIDEO_BYTE_MIN && file.size <= VIDEO_BYTE_MAX && isPassThroughMp4(bytes)) {
      if (duration > VIDEO_PASS_MAX_SECONDS) throw new Error("Use a video under 30 minutes.");
      return { contentType: "video/mp4", dataBase64: bytesToBase64(bytes) };
    }
    if (duration > VIDEO_DURATION_MAX_SECONDS) {
      throw new Error("Use a video under 90 seconds, or an MP4 already under 3 MB.");
    }
    const blob = options?.transcode
      ? await options.transcode(file)
      : await transcodePlayback(playback, duration);
    const prepared = new Uint8Array(await blob.arrayBuffer());
    if (prepared.length < VIDEO_BYTE_MIN) throw new Error("LinkedIn needs a video of at least 75 KB.");
    if (prepared.length > VIDEO_BYTE_MAX) throw new Error("The video must be under 3 MB.");
    if (!isPassThroughMp4(prepared)) throw new Error("The video could not be prepared.");
    return { contentType: "video/mp4", dataBase64: bytesToBase64(prepared) };
  } finally {
    playback?.release();
  }
}

function ascii(bytes: Uint8Array, start: number, end: number): string {
  let text = "";
  for (let index = start; index < end; index += 1) text += String.fromCharCode(bytes[index] ?? 0);
  return text;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
  }
  return btoa(binary);
}

function scaleToMaxEdge(width: number, height: number, maxEdge: number): { width: number; height: number } {
  const edge = Math.max(width, height);
  const scale = edge > maxEdge ? maxEdge / edge : 1;
  return { width: even(Math.round(width * scale)), height: even(Math.round(height * scale)) };
}

function even(value: number): number {
  const rounded = Math.max(2, value);
  return rounded - (rounded % 2);
}

function startVideoPlayback(file: File): Playback {
  const url = URL.createObjectURL(file);
  const video = document.createElement("video");
  video.playsInline = true;
  video.preload = "auto";
  video.src = url;
  const attempt = video.play?.();
  if (attempt && typeof attempt.catch === "function") {
    void attempt.catch(() => {
      video.muted = true;
      const retry = video.play?.();
      if (retry && typeof retry.catch === "function") void retry.catch(() => undefined);
    });
  }
  return {
    video,
    release() {
      video.pause();
      URL.revokeObjectURL(url);
    },
  };
}

async function readDuration(playback: Playback | null): Promise<number> {
  if (!playback) throw new Error("The video could not be read.");
  const video = playback.video;
  if (!(video.readyState >= 1 && Number.isFinite(video.duration) && video.duration > 0)) {
    await waitFor(video, "loadedmetadata", 30_000);
  }
  if (!Number.isFinite(video.duration) || video.duration <= 0) {
    throw new Error("The video could not be read.");
  }
  return video.duration;
}

async function transcodePlayback(playback: Playback | null, duration: number): Promise<Blob> {
  const mime = mp4RecorderMime();
  if (!playback || !mime) throw new Error(PREPARE_ERROR);
  const video = playback.video;
  const size = scaleToMaxEdge(video.videoWidth || 640, video.videoHeight || 360, 720);
  const canvas = document.createElement("canvas");
  canvas.width = size.width;
  canvas.height = size.height;
  const context = canvas.getContext("2d");
  const capture = canvas.captureStream?.bind(canvas);
  if (!context || !capture) throw new Error(PREPARE_ERROR);
  const picture = capture(24);
  const { stream, closeAudio } = mixAudio(video, picture);
  const options: MediaRecorderOptions = { mimeType: mime, videoBitsPerSecond: videoBitsPerSecond(duration) };
  if (stream.getAudioTracks().length > 0) options.audioBitsPerSecond = 64_000;
  let recorder: MediaRecorder;
  try {
    recorder = new MediaRecorder(stream, options);
  } catch {
    await closeAudio();
    throw new Error(PREPARE_ERROR);
  }
  const chunks: Blob[] = [];
  const stopped = new Promise<void>((resolve, reject) => {
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    recorder.onerror = () => reject(new Error("The video could not be read."));
    recorder.onstop = () => resolve();
  });
  let started = false;
  try {
    recorder.start(500);
    started = true;
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    await playFromStart(video);
    await waitUntilPlayed(video, duration, () => context.drawImage(video, 0, 0, canvas.width, canvas.height));
  } finally {
    if (started && recorder.state !== "inactive") recorder.stop();
    if (started) await stopped.catch(() => undefined);
    await closeAudio();
  }
  return new Blob(chunks, { type: "video/mp4" });
}

function mixAudio(video: HTMLVideoElement, picture: MediaStream): { stream: MediaStream; closeAudio: () => Promise<void> } {
  if (video.muted || typeof AudioContext === "undefined") {
    return { stream: picture, closeAudio: async () => undefined };
  }
  try {
    const audio = new AudioContext();
    const source = audio.createMediaElementSource(video);
    const dest = audio.createMediaStreamDestination();
    source.connect(dest);
    return {
      stream: new MediaStream([...picture.getVideoTracks(), ...dest.stream.getAudioTracks()]),
      closeAudio: () => audio.close().then(() => undefined).catch(() => undefined),
    };
  } catch {
    return { stream: picture, closeAudio: async () => undefined };
  }
}

async function playFromStart(video: HTMLVideoElement): Promise<void> {
  try {
    video.currentTime = 0;
  } catch {
    // A seek before metadata is ready still starts at the first frame.
  }
  try {
    await video.play();
  } catch {
    video.muted = true;
    await video.play();
  }
}

function waitUntilPlayed(video: HTMLVideoElement, duration: number, draw: () => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(finish, (duration + 5) * 1000);
    function finish() {
      clearTimeout(timer);
      video.removeEventListener("ended", finish);
      video.removeEventListener("error", fail);
      resolve();
    }
    function fail() {
      clearTimeout(timer);
      video.removeEventListener("ended", finish);
      video.removeEventListener("error", fail);
      reject(new Error("The video could not be read."));
    }
    video.addEventListener("ended", finish);
    video.addEventListener("error", fail);
    const frame = () => {
      draw();
      if (video.ended || video.currentTime >= duration - 0.05) {
        finish();
        return;
      }
      requestAnimationFrame(frame);
    };
    frame();
  });
}

function waitFor(video: HTMLVideoElement, event: string, ms: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error("The video could not be read."));
    }, ms);
    const ok = () => {
      cleanup();
      resolve();
    };
    const bad = () => {
      cleanup();
      reject(new Error("The video could not be read."));
    };
    const cleanup = () => {
      clearTimeout(timer);
      video.removeEventListener(event, ok);
      video.removeEventListener("error", bad);
    };
    video.addEventListener(event, ok);
    video.addEventListener("error", bad);
  });
}
