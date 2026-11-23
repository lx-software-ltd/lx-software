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
  transcode?: (file: File, bitsPerSecond: number) => Promise<Blob>;
  signal?: AbortSignal;
  onProgress?: (fraction: number) => void;
};

type Playback = {
  video: HTMLVideoElement;
  routed: RoutedAudio | null;
  release: () => void;
};

type RoutedAudio = {
  dest: { stream: MediaStream };
  close: () => Promise<void>;
};

type Mp4Facts = {
  brand: string | null;
  avc: boolean;
  hevc: boolean;
};

const AUDIO_BITS_PER_SECOND = 64_000;
const BITRATE_TARGET = 0.7;
const VIDEO_BITRATE_MIN = 80_000;
const VIDEO_BITRATE_MAX = 1_200_000;
const STALL_MS = 20_000;
/** Brands a browser recorder writes for an H.264 MP4. Safari's is `iso5`. */
const RECORDER_BRANDS = new Set(["isom", "iso2", "iso4", "iso5", "iso6", "mp41", "mp42", "avc1", "M4V ", "mp71"]);
const CONTAINERS = new Set(["moov", "trak", "mdia", "minf", "stbl", "edts", "mvex", "moof", "traf"]);
const PREPARE_ERROR = "This browser cannot prepare that video. Export an MP4 under 3 MB.";

export class VideoPrepareCancelled extends Error {
  constructor() {
    super("Cancelled.");
    this.name = "VideoPrepareCancelled";
  }
}

export function mp4MajorBrand(bytes: Uint8Array): string | null {
  if (bytes.length < 12) return null;
  if (ascii(bytes, 4, 8) !== "ftyp") return null;
  return ascii(bytes, 8, 12);
}

/** True when the file is already an H.264 MP4 LinkedIn can play. QuickTime and HEVC are not. */
export function isPassThroughMp4(bytes: Uint8Array): boolean {
  const facts = inspectMp4(bytes);
  if (!facts.brand || facts.hevc || facts.brand === "qt  " || !facts.avc) return false;
  return true;
}

/**
 * Bits per second for the picture, after the audio track and encoder headroom.
 * The browser treats the value as a hint, so the caller retries once if the file is still too big.
 */
export function videoBitsPerSecond(
  durationSeconds: number,
  byteMax = VIDEO_BYTE_MAX,
  audioBitsPerSecond = AUDIO_BITS_PER_SECOND,
): number {
  const seconds = Math.max(durationSeconds, 0.1);
  const audioBytes = (audioBitsPerSecond * seconds) / 8;
  const budgetBytes = byteMax * BITRATE_TARGET - audioBytes;
  const bits = Math.floor((Math.max(budgetBytes, 1) * 8) / seconds);
  return Math.min(VIDEO_BITRATE_MAX, Math.max(VIDEO_BITRATE_MIN, bits));
}

/** A hidden tab does not count as a stall. Playback is paused with the page, not cut off. */
export function stallExpired(elapsedMs: number, hidden: boolean): boolean {
  return !hidden && elapsedMs > STALL_MS;
}

export function playbackDone(currentTime: number, duration: number, ended: boolean): boolean {
  return ended || currentTime >= duration - 0.05;
}

export function mp4RecorderMime(): string | null {
  if (typeof MediaRecorder === "undefined") return null;
  if (typeof MediaRecorder.isTypeSupported !== "function") return "video/mp4";
  return MediaRecorder.isTypeSupported("video/mp4") ? "video/mp4" : null;
}

/**
 * Store an H.264 MP4 that already fits, or re-encode a camera clip.
 * Playback starts before the first await so an iPad gesture can begin the video.
 * The audio graph is attached first, so the clip does not play through the speakers.
 */
export async function prepareLinkedInVideo(file: File, options?: VideoPrepare): Promise<LinkedInVideoUpload> {
  if (!file.size) throw new Error("The video is empty.");
  if (file.size > VIDEO_SOURCE_BYTE_MAX) {
    throw new Error("That video is too large to prepare here. Use a file under 80 MB.");
  }
  throwIfCancelled(options?.signal);
  const playback = options?.durationSeconds ? null : beginPlayback(file);
  try {
    throwIfCancelled(options?.signal);
    const facts = await untilCancelled(inspectFile(file), options?.signal);
    throwIfCancelled(options?.signal);
    const duration = await untilCancelled(
      options?.durationSeconds ? options.durationSeconds(file) : readDuration(playback),
      options?.signal,
    );
    if (!Number.isFinite(duration) || duration < VIDEO_DURATION_MIN_SECONDS) {
      throw new Error("LinkedIn needs a video of at least 3 seconds.");
    }
    if (file.size >= VIDEO_BYTE_MIN && file.size <= VIDEO_BYTE_MAX && canStore(facts)) {
      if (duration > VIDEO_PASS_MAX_SECONDS) throw new Error("Use a video under 30 minutes.");
      const bytes = new Uint8Array(await file.arrayBuffer());
      return { contentType: "video/mp4", dataBase64: bytesToBase64(bytes) };
    }
    if (duration > VIDEO_DURATION_MAX_SECONDS) {
      throw new Error("Use a video under 90 seconds, or an MP4 already under 3 MB.");
    }
    const prepared = await encodeUnderCap(file, playback, duration, options);
    if (prepared.length < VIDEO_BYTE_MIN) throw new Error("LinkedIn needs a video of at least 75 KB.");
    if (!isRecorderMp4(prepared)) throw new Error("The video could not be prepared.");
    return { contentType: "video/mp4", dataBase64: bytesToBase64(prepared) };
  } finally {
    playback?.release();
  }
}

function canStore(facts: Mp4Facts): boolean {
  return Boolean(facts.brand && facts.avc && !facts.hevc && facts.brand !== "qt  ");
}

function isRecorderMp4(bytes: Uint8Array): boolean {
  const facts = inspectMp4(bytes);
  if (!facts.brand || facts.hevc || facts.brand === "qt  ") return false;
  if (facts.avc) return true;
  return RECORDER_BRANDS.has(facts.brand);
}

async function encodeUnderCap(
  file: File,
  playback: Playback | null,
  duration: number,
  options?: VideoPrepare,
): Promise<Uint8Array> {
  let bits = videoBitsPerSecond(duration);
  let prepared = await encodeOnce(file, playback, duration, bits, options);
  if (prepared.length > VIDEO_BYTE_MAX) {
    bits = Math.max(VIDEO_BITRATE_MIN, Math.floor(bits / 2));
    prepared = await encodeOnce(file, playback, duration, bits, options);
  }
  if (prepared.length > VIDEO_BYTE_MAX) throw new Error("The video must be under 3 MB.");
  return prepared;
}

async function encodeOnce(
  file: File,
  playback: Playback | null,
  duration: number,
  bits: number,
  options?: VideoPrepare,
): Promise<Uint8Array> {
  throwIfCancelled(options?.signal);
  const blob = options?.transcode
    ? await options.transcode(file, bits)
    : await transcodePlayback(playback, duration, bits, options);
  throwIfCancelled(options?.signal);
  return new Uint8Array(await blob.arrayBuffer());
}

function throwIfCancelled(signal?: AbortSignal): void {
  if (signal?.aborted) throw new VideoPrepareCancelled();
}

function untilCancelled<T>(work: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return work;
  return new Promise((resolve, reject) => {
    const fail = () => reject(new VideoPrepareCancelled());
    if (signal.aborted) {
      fail();
      return;
    }
    const onAbort = () => {
      signal.removeEventListener("abort", onAbort);
      fail();
    };
    signal.addEventListener("abort", onAbort);
    work.then(
      (value) => {
        signal.removeEventListener("abort", onAbort);
        resolve(value);
      },
      (error) => {
        signal.removeEventListener("abort", onAbort);
        reject(error);
      },
    );
  });
}

function inspectMp4(bytes: Uint8Array): Mp4Facts {
  const facts: Mp4Facts = { brand: mp4MajorBrand(bytes), avc: false, hevc: false };
  walkBoxes(bytes, 0, bytes.length, facts, 0);
  return facts;
}

async function inspectFile(file: File): Promise<Mp4Facts> {
  const facts: Mp4Facts = { brand: null, avc: false, hevc: false };
  const head = await readSlice(file, 0, 32);
  facts.brand = mp4MajorBrand(head);
  let offset = 0;
  for (let guard = 0; guard < 32 && offset + 8 <= file.size; guard += 1) {
    const boxHead = await readSlice(file, offset, 16);
    const parsed = readBoxHeader(boxHead, file.size - offset);
    if (!parsed || parsed.size === 0 || parsed.type.trim() === "") break;
    if (parsed.type === "moov" && parsed.size <= 8_000_000) {
      const moov = await readSlice(file, offset, parsed.size);
      walkBoxes(moov, 0, moov.length, facts, 0);
      return facts;
    }
    noteCodec(parsed.type, facts);
    offset += parsed.size;
  }
  return facts;
}

async function readSlice(file: File, start: number, length: number): Promise<Uint8Array> {
  const end = Math.min(file.size, start + length);
  return new Uint8Array(await file.slice(start, end).arrayBuffer());
}

function walkBoxes(bytes: Uint8Array, start: number, end: number, facts: Mp4Facts, depth: number): void {
  let offset = start;
  while (offset + 8 <= end && depth < 12) {
    const header = readBoxHeader(bytes.subarray(offset, Math.min(end, offset + 16)), end - offset);
    if (!header || header.size < header.header) return;
    noteCodec(header.type, facts);
    const extra = header.type === "stsd" ? 8 : 0;
    if (CONTAINERS.has(header.type) || header.type === "stsd") {
      const child = offset + header.header + extra;
      const boxEnd = header.size === 0 ? end : Math.min(end, offset + header.size);
      if (child < boxEnd) walkBoxes(bytes, child, boxEnd, facts, depth + 1);
    }
    if (header.size === 0) return;
    offset += header.size;
  }
}

function readBoxHeader(bytes: Uint8Array, remaining: number): { type: string; size: number; header: number } | null {
  if (bytes.length < 8) return null;
  let size = u32(bytes, 0);
  let header = 8;
  if (size === 1) {
    if (bytes.length < 16) return null;
    size = u64(bytes, 8);
    header = 16;
  }
  if (size === 0) size = remaining;
  return { type: ascii(bytes, 4, 8), size, header };
}

function noteCodec(type: string, facts: Mp4Facts): void {
  if (type === "avc1" || type === "avc3") facts.avc = true;
  if (type === "hvc1" || type === "hev1" || type === "dvh1" || type === "dvhe") facts.hevc = true;
}

function u32(bytes: Uint8Array, offset: number): number {
  return (
    ((bytes[offset] ?? 0) * 0x1000000 +
      (bytes[offset + 1] ?? 0) * 0x10000 +
      (bytes[offset + 2] ?? 0) * 0x100 +
      (bytes[offset + 3] ?? 0)) >>>
    0
  );
}

function u64(bytes: Uint8Array, offset: number): number {
  return u32(bytes, offset) * 2 ** 32 + u32(bytes, offset + 4);
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

function beginPlayback(file: File): Playback {
  const url = URL.createObjectURL(file);
  const video = document.createElement("video");
  video.playsInline = true;
  video.preload = "auto";
  video.src = url;
  const routed = routeAudio(video);
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
    routed,
    release() {
      video.pause();
      URL.revokeObjectURL(url);
      void routed?.close();
    },
  };
}

function routeAudio(video: HTMLVideoElement): RoutedAudio | null {
  const Ctx = window.AudioContext;
  if (!Ctx) return null;
  try {
    const audio = new Ctx();
    const source = audio.createMediaElementSource(video);
    const dest = audio.createMediaStreamDestination();
    source.connect(dest);
    return {
      dest,
      close: () => audio.close().then(() => undefined).catch(() => undefined),
    };
  } catch {
    return null;
  }
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

async function transcodePlayback(
  playback: Playback | null,
  duration: number,
  bits: number,
  options?: VideoPrepare,
): Promise<Blob> {
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
  const { stream, closeAudio } = mixAudio(picture, playback.routed);
  const recorderOptions: MediaRecorderOptions = { mimeType: mime, videoBitsPerSecond: bits };
  if (stream.getAudioTracks().length > 0) recorderOptions.audioBitsPerSecond = AUDIO_BITS_PER_SECOND;
  let recorder: MediaRecorder;
  try {
    recorder = new MediaRecorder(stream, recorderOptions);
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
    throwIfCancelled(options?.signal);
    recorder.start(500);
    started = true;
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    await playFromStart(video);
    await waitUntilPlayed(video, duration, () => context.drawImage(video, 0, 0, canvas.width, canvas.height), options);
  } finally {
    if (started && recorder.state !== "inactive") recorder.stop();
    if (started) await stopped.catch(() => undefined);
    await closeAudio();
  }
  return new Blob(chunks, { type: "video/mp4" });
}

function mixAudio(
  picture: MediaStream,
  routed: RoutedAudio | null,
): { stream: MediaStream; closeAudio: () => Promise<void> } {
  if (!routed) return { stream: picture, closeAudio: async () => undefined };
  const tracks = routed.dest.stream.getAudioTracks();
  if (tracks.length === 0) return { stream: picture, closeAudio: routed.close };
  return {
    stream: new MediaStream([...picture.getVideoTracks(), ...tracks]),
    closeAudio: routed.close,
  };
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

function waitUntilPlayed(
  video: HTMLVideoElement,
  duration: number,
  draw: () => void,
  options?: VideoPrepare,
): Promise<void> {
  return new Promise((resolve, reject) => {
    let lastTime = video.currentTime;
    let lastAdvance = performance.now();
    let settled = false;
    const resumeClock = () => {
      lastAdvance = performance.now();
    };
    const stop = (done: () => void) => {
      if (settled) return;
      settled = true;
      video.removeEventListener("ended", finish);
      video.removeEventListener("error", fail);
      document.removeEventListener("visibilitychange", resumeClock);
      done();
    };
    const finish = () => stop(resolve);
    const fail = () => stop(() => reject(new Error("The video could not be read.")));
    video.addEventListener("ended", finish);
    video.addEventListener("error", fail);
    document.addEventListener("visibilitychange", resumeClock);
    const frame = () => {
      if (settled) return;
      if (options?.signal?.aborted) {
        stop(() => reject(new VideoPrepareCancelled()));
        return;
      }
      draw();
      options?.onProgress?.(Math.min(1, duration > 0 ? video.currentTime / duration : 0));
      const hidden = typeof document !== "undefined" && document.hidden;
      if (playbackDone(video.currentTime, duration, video.ended)) {
        finish();
        return;
      }
      if (hidden) {
        lastAdvance = performance.now();
      } else if (video.currentTime > lastTime + 0.01) {
        lastTime = video.currentTime;
        lastAdvance = performance.now();
      } else if (stallExpired(performance.now() - lastAdvance, hidden)) {
        stop(() => reject(new Error("The video could not be read.")));
        return;
      }
      if (!hidden && video.paused) void video.play?.().catch(() => undefined);
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
