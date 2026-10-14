import { describe, expect, it } from "vitest";
import { IMAGE_BYTE_MAX, IMAGE_SOURCE_BYTE_MAX } from "./linkedinModel";
import {
  fitLinkedInImage,
  nextEncodeStep,
  scaleToMaxEdge,
  shrinkLinkedInImage,
} from "./fitLinkedInImage";

function jpegFile(bytes: number, name = "photo.jpg"): File {
  const data = new Uint8Array(bytes);
  data[0] = 0xff;
  data[1] = 0xd8;
  data[2] = 0xff;
  return new File([data], name, { type: "image/jpeg" });
}

describe("fitLinkedInImage", () => {
  it("mirrors the stored LinkedIn image cap", () => {
    expect(IMAGE_BYTE_MAX).toBe(1_500_000);
    expect(IMAGE_SOURCE_BYTE_MAX).toBe(25_000_000);
  });

  it("passes through a JPEG already under the cap", async () => {
    const file = jpegFile(200);
    const result = await fitLinkedInImage(file);
    expect(result.contentType).toBe("image/jpeg");
    expect(atob(result.dataBase64).length).toBe(200);
  });

  it("rejects a file that is not a PNG or JPEG", async () => {
    const file = new File([new Uint8Array(10)], "notes.txt", { type: "text/plain" });
    await expect(fitLinkedInImage(file)).rejects.toThrow("Use a PNG or JPEG image.");
  });

  it("rejects an empty file", async () => {
    const file = new File([], "empty.jpg", { type: "image/jpeg" });
    await expect(fitLinkedInImage(file)).rejects.toThrow("The image must be under 1.5 MB.");
  });

  it("rejects a source file over the browser decode cap", async () => {
    const file = jpegFile(IMAGE_SOURCE_BYTE_MAX + 1, "huge.jpg");
    await expect(fitLinkedInImage(file)).rejects.toThrow("under 25 MB");
  });

  it("shrinks a JPEG over the stored cap instead of rejecting it", async () => {
    const file = jpegFile(IMAGE_BYTE_MAX + 1);
    const result = await fitLinkedInImage(file, async () => ({
      contentType: "image/jpeg",
      dataBase64: "c2hydW5r",
    }));
    expect(result).toEqual({ contentType: "image/jpeg", dataBase64: "c2hydW5r" });
  });
});

describe("nextEncodeStep", () => {
  it("drops JPEG quality before shrinking the frame", () => {
    expect(nextEncodeStep(1600, 1200, 0.88)).toEqual({ width: 1600, height: 1200, quality: 0.73 });
    expect(nextEncodeStep(1600, 1200, 0.52)).toEqual({ width: 1360, height: 1020, quality: 0.85 });
  });

  it("stops before the short edge drops under 320", () => {
    expect(nextEncodeStep(360, 360, 0.5)).toBeNull();
  });
});

describe("scaleToMaxEdge", () => {
  it("leaves a feed-sized frame alone and scales a 4K photo", () => {
    expect(scaleToMaxEdge(1200, 1200)).toEqual({ width: 1200, height: 1200 });
    expect(scaleToMaxEdge(4000, 3000)).toEqual({ width: 1600, height: 1200 });
  });
});

describe("shrinkLinkedInImage", () => {
  it("retries encode until the JPEG is under the stored cap", async () => {
    const file = jpegFile(IMAGE_BYTE_MAX + 50_000);
    let calls = 0;
    const result = await shrinkLinkedInImage(file, {
      width: 4000,
      height: 3000,
      encode: async () => {
        calls += 1;
        const size = calls === 1 ? 2_000_000 : 400_000;
        return new Blob([new Uint8Array(size)], { type: "image/jpeg" });
      },
    });
    expect(calls).toBe(2);
    expect(result.contentType).toBe("image/jpeg");
    expect(atob(result.dataBase64).length).toBe(400_000);
  });
});
