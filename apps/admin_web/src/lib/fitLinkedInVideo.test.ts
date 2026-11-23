import { describe, expect, it, vi } from "vitest";
import { VIDEO_BYTE_MAX, VIDEO_BYTE_MIN, VIDEO_SOURCE_BYTE_MAX } from "./linkedinModel";
import {
  isPassThroughMp4,
  mp4MajorBrand,
  prepareLinkedInVideo,
  videoBitsPerSecond,
} from "./fitLinkedInVideo";

function videoBytes(size: number, brand: string): Uint8Array {
  const data = new Uint8Array(size);
  data.set([0x66, 0x74, 0x79, 0x70], 4);
  data.set(Array.from(brand).map((char) => char.charCodeAt(0)), 8);
  return data;
}

function videoFile(size: number, brand: string, name: string, type = ""): File {
  return new File([videoBytes(size, brand)], name, { type });
}

describe("prepareLinkedInVideo", () => {
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
  it("targets the stored cap and stays inside a usable range", () => {
    expect(VIDEO_BYTE_MAX).toBe(3_000_000);
    expect(videoBitsPerSecond(10)).toBe(1_200_000);
    expect(videoBitsPerSecond(30)).toBe(680_000);
    expect(videoBitsPerSecond(90)).toBe(250_000);
  });
});
