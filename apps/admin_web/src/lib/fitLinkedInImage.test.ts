import { describe, expect, it, vi } from "vitest";
import { IMAGE_BYTE_MAX, IMAGE_SOURCE_BYTE_MAX } from "./linkedinModel";
import {
  downsampleSteps,
  fitLinkedInImage,
  jpegBlobFromCanvas,
  nextEncodeStep,
  paintLinkedInFrame,
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

  it("treats a photo with no type and a .jpeg name as a JPEG", async () => {
    const file = new File([new Uint8Array([0xff, 0xd8, 1])], "photo.jpeg", { type: "" });
    const result = await fitLinkedInImage(file);
    expect(result.contentType).toBe("image/jpeg");
    expect(atob(result.dataBase64).length).toBe(3);
  });

  it("treats an iPad image/jpg as a JPEG", async () => {
    const file = new File([new Uint8Array([0xff, 0xd8, 1])], "photo.jpg", { type: "image/jpg" });
    const result = await fitLinkedInImage(file);
    expect(result.contentType).toBe("image/jpeg");
    expect(atob(result.dataBase64).length).toBe(3);
  });

  it("re-encodes a HEIC photo instead of storing it", async () => {
    const file = new File([new Uint8Array(100)], "photo.heic", { type: "image/heic" });
    const result = await fitLinkedInImage(file, async () => ({
      contentType: "image/jpeg",
      dataBase64: "aGVpYw",
    }));
    expect(result).toEqual({ contentType: "image/jpeg", dataBase64: "aGVpYw" });
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
    await expect(fitLinkedInImage(file)).rejects.toThrow("The image is empty.");
  });

  it("sends a PNG over the cap through the shrink path", async () => {
    const file = new File([new Uint8Array(IMAGE_BYTE_MAX + 1)], "wide.png", { type: "image/png" });
    const result = await fitLinkedInImage(file, async () => ({
      contentType: "image/jpeg",
      dataBase64: "cG5n",
    }));
    expect(result).toEqual({ contentType: "image/jpeg", dataBase64: "cG5n" });
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
  it("shrinks the frame before JPEG quality falls below 0.7", () => {
    expect(nextEncodeStep(1600, 1200, 0.85)).toEqual({ width: 1360, height: 1020, quality: 0.85 });
    expect(nextEncodeStep(360, 360, 0.85)).toEqual({ width: 360, height: 360, quality: 0.8 });
  });

  it("stops before the short edge drops under 320 or quality under 0.7", () => {
    expect(nextEncodeStep(360, 360, 0.7)).toBeNull();
  });
});

describe("paintLinkedInFrame", () => {
  it("fills the canvas white before drawing so a transparent PNG does not turn black", () => {
    const order: string[] = [];
    const context = {
      fillStyle: "",
      fillRect(this: { fillStyle: string }, _x: number, _y: number, width: number, height: number) {
        order.push(`fill:${this.fillStyle}:${width}x${height}`);
      },
      drawImage() {
        order.push("draw");
      },
    };
    paintLinkedInFrame(context as unknown as CanvasRenderingContext2D, {} as CanvasImageSource, 10, 8);
    expect(order).toEqual(["fill:#ffffff:10x8", "draw"]);
  });
});

describe("downsampleSteps", () => {
  it("halves an iPad original before the final frame, and stays under the canvas edge", () => {
    expect(downsampleSteps(4032, 3024, 1600, 1200)).toEqual([{ width: 2016, height: 1512 }]);
    const steps = downsampleSteps(12000, 9000, 1600, 1200);
    expect(steps[0]).toEqual({ width: 4096, height: 3072 });
    for (const step of steps) {
      expect(step.width).toBeLessThanOrEqual(4096);
      expect(step.height).toBeLessThanOrEqual(4096);
    }
    expect(steps.at(-1)?.width).toBeLessThanOrEqual(3200);
  });
});

describe("jpegBlobFromCanvas", () => {
  it("reads the canvas another way when toBlob returns null, as Safari does on iPad", async () => {
    const canvas = document.createElement("canvas");
    const toBlob = vi.spyOn(canvas, "toBlob").mockImplementation((callback) => {
      callback(null);
    });
    const toDataURL = vi.spyOn(canvas, "toDataURL").mockReturnValue(`data:image/jpeg;base64,${btoa("ipad")}`);
    const blob = await jpegBlobFromCanvas(canvas, 0.85);
    expect(toBlob).toHaveBeenCalled();
    expect(toDataURL).toHaveBeenCalledWith("image/jpeg", 0.85);
    expect(await blob.text()).toBe("ipad");
    toBlob.mockRestore();
    toDataURL.mockRestore();
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
    const seen: { width: number; height: number; quality: number }[] = [];
    const result = await shrinkLinkedInImage(file, {
      width: 4000,
      height: 3000,
      encode: async (width, height, quality) => {
        calls += 1;
        seen.push({ width, height, quality });
        const size = calls === 1 ? 2_000_000 : 400_000;
        return new Blob([new Uint8Array(size)], { type: "image/jpeg" });
      },
    });
    expect(seen).toEqual([
      { width: 1600, height: 1200, quality: 0.85 },
      { width: 1360, height: 1020, quality: 0.85 },
    ]);
    expect(result.contentType).toBe("image/jpeg");
    expect(atob(result.dataBase64).length).toBe(400_000);
  });

  it("keeps the object URL until encoding has finished", async () => {
    const events: string[] = [];
    const create = vi.spyOn(URL, "createObjectURL").mockImplementation(() => {
      events.push("create");
      return "blob:photo";
    });
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {
      events.push("revoke");
    });
    const getContext = vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => {
      events.push("encode");
      return null;
    });
    class FakeImage {
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      naturalWidth = 800;
      naturalHeight = 600;
      width = 800;
      height = 600;
      set src(_value: string) {
        events.push("src");
        this.onload?.();
      }
    }
    vi.stubGlobal("Image", FakeImage);
    try {
      await expect(shrinkLinkedInImage(jpegFile(IMAGE_BYTE_MAX + 1))).rejects.toThrow(
        "The picture could not be read.",
      );
      expect(events).toEqual(["create", "src", "encode", "revoke"]);
    } finally {
      create.mockRestore();
      revoke.mockRestore();
      getContext.mockRestore();
      vi.unstubAllGlobals();
    }
  });
});
