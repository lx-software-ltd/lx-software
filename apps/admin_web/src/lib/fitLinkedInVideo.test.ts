import { afterEach, describe, expect, it, vi } from "vitest";
import { VIDEO_BYTE_MAX, VIDEO_BYTE_MIN, VIDEO_SOURCE_BYTE_MAX } from "./linkedinModel";
import {
  isPassThroughMp4,
  mp4MajorBrand,
  playbackDone,
  prepareLinkedInVideo,
  stallExpired,
  videoBitsPerSecond,
  VideoPrepareCancelled,
} from "./fitLinkedInVideo";

function fourcc(text: string): number[] {
  return Array.from(text.padEnd(4, " ").slice(0, 4)).map((char) => char.charCodeAt(0));
}

function box(type: string, payload: number[]): number[] {
  const size = 8 + payload.length;
  return [(size >>> 24) & 255, (size >>> 16) & 255, (size >>> 8) & 255, size & 255, ...fourcc(type), ...payload];
}

function videoBytes(size: number, brand: string, codec: "avc1" | "hvc1" | "none" = "avc1"): Uint8Array {
  const ftyp = box("ftyp", [...fourcc(brand), 0, 0, 0, 0]);
  const nested = codec === "none" ? ftyp : [...ftyp, ...box("moov", box(codec, []))];
  const data = new Uint8Array(Math.max(size, nested.length));
  data.set(nested);
  return data.subarray(0, Math.max(size, nested.length));
}

function videoFile(size: number, brand: string, name: string, type = "", codec: "avc1" | "hvc1" | "none" = "avc1"): File {
  return new File([videoBytes(size, brand, codec)], name, { type });
}

describe("prepareLinkedInVideo", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("keeps an H.264 MP4 already inside the stored cap", async () => {
    const transcode = vi.fn();
    const file = videoFile(VIDEO_BYTE_MIN, "isom", "clip.mp4", "video/mp4");
    const result = await prepareLinkedInVideo(file, {
      durationSeconds: async () => 12,
      transcode,
    });
    expect(transcode).not.toHaveBeenCalled();
    expect(result.contentType).toBe("video/mp4");
    expect(atob(result.dataBase64).length).toBe(VIDEO_BYTE_MIN);
    expect(isPassThroughMp4(videoBytes(VIDEO_BYTE_MIN, "isom"))).toBe(true);
    expect(mp4MajorBrand(videoBytes(32, "qt  "))).toBe("qt  ");
  });

  it("prepares an iPad QuickTime movie instead of storing it", async () => {
    const prepared = videoBytes(VIDEO_BYTE_MIN, "mp42");
    const transcode = vi.fn(async () => new Blob([prepared], { type: "video/mp4" }));
    const file = videoFile(120_000, "qt  ", "IMG_1234.MOV", "");
    const result = await prepareLinkedInVideo(file, {
      durationSeconds: async () => 8,
      transcode,
    });
    expect(transcode).toHaveBeenCalledOnce();
    expect(result.contentType).toBe("video/mp4");
    expect(atob(result.dataBase64).length).toBe(VIDEO_BYTE_MIN);
  });

  it("accepts the iso5 brand Safari records when the codec is not HEVC", async () => {
    const prepared = videoBytes(VIDEO_BYTE_MIN, "iso5", "none");
    const transcode = vi.fn(async () => new Blob([prepared], { type: "video/mp4" }));
    const file = videoFile(120_000, "qt  ", "IMG_1234.MOV", "video/quicktime");
    const result = await prepareLinkedInVideo(file, {
      durationSeconds: async () => 8,
      transcode,
    });
    expect(result.contentType).toBe("video/mp4");
    expect(isPassThroughMp4(videoBytes(VIDEO_BYTE_MIN, "isom", "hvc1"))).toBe(false);
    expect(isPassThroughMp4(videoBytes(VIDEO_BYTE_MIN, "mp42", "hvc1"))).toBe(false);
  });

  it("re-encodes an HEVC MP4 even when the brand looks like H.264", async () => {
    const transcode = vi.fn(async () => new Blob([videoBytes(VIDEO_BYTE_MIN, "iso5")], { type: "video/mp4" }));
    const file = videoFile(VIDEO_BYTE_MIN, "isom", "clip.mp4", "video/mp4", "hvc1");
    await prepareLinkedInVideo(file, { durationSeconds: async () => 8, transcode });
    expect(transcode).toHaveBeenCalledOnce();
  });

  it("reads only the header of a camera clip that will be re-encoded", async () => {
    const file = videoFile(120_000, "qt  ", "IMG_1.MOV", "video/quicktime");
    const original = file.arrayBuffer.bind(file);
    let fullReads = 0;
    file.arrayBuffer = () => {
      fullReads += 1;
      return original();
    };
    await prepareLinkedInVideo(file, {
      durationSeconds: async () => 8,
      transcode: async () => new Blob([videoBytes(VIDEO_BYTE_MIN, "iso5")], { type: "video/mp4" }),
    });
    expect(fullReads).toBe(0);
  });

  it("retries once when the encoder overshoots the cap", async () => {
    const rates: number[] = [];
    const transcode = vi.fn(async (_file: File, bits: number) => {
      rates.push(bits);
      const bytes = rates.length === 1 ? videoBytes(VIDEO_BYTE_MAX + 1, "iso5") : videoBytes(VIDEO_BYTE_MIN, "iso5");
      return new Blob([bytes], { type: "video/mp4" });
    });
    const file = videoFile(120_000, "qt  ", "long.mov", "video/quicktime");
    const result = await prepareLinkedInVideo(file, { durationSeconds: async () => 60, transcode });
    expect(rates).toHaveLength(2);
    expect(rates[1]).toBeLessThan(rates[0] ?? 0);
    expect(atob(result.dataBase64).length).toBe(VIDEO_BYTE_MIN);
  });

  it("routes audio before the clip plays, and cancel stops the prepare", async () => {
    const events: string[] = [];
    const controller = new AbortController();
    class FakeAudioContext {
      createMediaElementSource() {
        events.push("route");
        return { connect() {} };
      }
      createMediaStreamDestination() {
        return { stream: { getAudioTracks: () => [] } };
      }
      close() {
        return Promise.resolve();
      }
    }
    vi.stubGlobal("AudioContext", FakeAudioContext);
    vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function play(this: HTMLMediaElement) {
      events.push(this.muted ? "play-muted" : "play");
      controller.abort();
      return Promise.resolve();
    });
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:clip");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const file = videoFile(120_000, "qt  ", "IMG_9.MOV", "video/quicktime");
    await expect(prepareLinkedInVideo(file, { signal: controller.signal })).rejects.toBeInstanceOf(VideoPrepareCancelled);
    expect(events).toEqual(["route", "play"]);
  });

  it("rejects a clip LinkedIn will not take", async () => {
    const file = videoFile(VIDEO_BYTE_MIN, "isom", "short.mp4", "video/mp4");
    await expect(
      prepareLinkedInVideo(file, { durationSeconds: async () => 2, transcode: async () => new Blob() }),
    ).rejects.toThrow("at least 3 seconds");
    const movie = videoFile(120_000, "qt  ", "long.mov", "video/quicktime");
    await expect(
      prepareLinkedInVideo(movie, { durationSeconds: async () => 120, transcode: async () => new Blob() }),
    ).rejects.toThrow("under 90 seconds");
  });

  it("rejects a source video over the browser cap before preparing it", async () => {
    const file = videoFile(32, "qt  ", "huge.mov", "video/quicktime");
    Object.defineProperty(file, "size", { value: VIDEO_SOURCE_BYTE_MAX + 1 });
    await expect(prepareLinkedInVideo(file)).rejects.toThrow("under 80 MB");
  });

  it("asks for an MP4 when this browser cannot prepare a camera video", async () => {
    const file = videoFile(120_000, "qt  ", "IMG_9.MOV", "video/quicktime");
    await expect(prepareLinkedInVideo(file, { durationSeconds: async () => 6 })).rejects.toThrow(
      "Export an MP4 under 3 MB",
    );
  });
});

describe("videoBitsPerSecond", () => {
  it("keeps the audio inside the stored cap", () => {
    expect(VIDEO_BYTE_MAX).toBe(3_000_000);
    expect(videoBitsPerSecond(10)).toBe(1_200_000);
    expect(videoBitsPerSecond(30)).toBe(496_000);
    expect(videoBitsPerSecond(60)).toBe(216_000);
    expect(videoBitsPerSecond(90)).toBe(122_666);
    for (const seconds of [60, 90]) {
      const bytes = ((videoBitsPerSecond(seconds) + 64_000) * seconds) / 8;
      expect(bytes).toBeLessThanOrEqual(VIDEO_BYTE_MAX * 0.7);
    }
  });

  it("does not finish a clip early while the tab is hidden", () => {
    expect(stallExpired(30_000, true)).toBe(false);
    expect(stallExpired(30_000, false)).toBe(true);
    expect(playbackDone(1, 90, false)).toBe(false);
    expect(playbackDone(89.96, 90, false)).toBe(true);
  });
});
