import { unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";

test("a real canvas photo stays under 1.5 MB and a transparent PNG is matted white", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "one Chromium canvas pass");
  test.setTimeout(90_000);
  await page.goto("/");

  const result = await page.evaluate(async () => {
    const { fitLinkedInImage } = await import("/src/lib/fitLinkedInImage.ts");
    const cap = 1_500_000;

    function noiseCanvas(size: number, transparentEdge: boolean): HTMLCanvasElement {
      const canvas = document.createElement("canvas");
      canvas.width = size;
      canvas.height = size;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("no canvas");
      const data = context.createImageData(size, size);
      for (let index = 0; index < data.data.length; index += 4) {
        const pixel = index / 4;
        const x = pixel % size;
        const y = Math.floor(pixel / size);
        const edge = x < 48 || y < 48;
        data.data[index] = (Math.random() * 255) | 0;
        data.data[index + 1] = (Math.random() * 255) | 0;
        data.data[index + 2] = (Math.random() * 255) | 0;
        data.data[index + 3] = transparentEdge && edge ? 0 : 255;
      }
      context.putImageData(data, 0, 0);
      return canvas;
    }

    function blobFile(canvas: HTMLCanvasElement, type: string, name: string, quality?: number): Promise<File> {
      return new Promise((resolve, reject) => {
        canvas.toBlob(
          (blob) => (blob ? resolve(new File([blob], name, { type })) : reject(new Error("empty blob"))),
          type,
          quality,
        );
      });
    }

    async function fileOverCap(type: "image/jpeg" | "image/png"): Promise<File> {
      for (const size of [1200, 1600]) {
        const canvas = noiseCanvas(size, type === "image/png");
        const file = await blobFile(canvas, type, type === "image/png" ? "edge.png" : "noise.jpg", 0.95);
        if (file.size > cap) return file;
      }
      throw new Error(`could not build a ${type} over 1.5 MB`);
    }

    async function corner(dataBase64: string): Promise<[number, number, number]> {
      const image = new Image();
      await new Promise<void>((resolve, reject) => {
        image.onload = () => resolve();
        image.onerror = () => reject(new Error("fitted image could not be read"));
        image.src = `data:image/jpeg;base64,${dataBase64}`;
      });
      const canvas = document.createElement("canvas");
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("no canvas");
      context.drawImage(image, 0, 0);
      const pixel = context.getImageData(0, 0, 1, 1).data;
      return [pixel[0], pixel[1], pixel[2]];
    }

    const jpeg = await fileOverCap("image/jpeg");
    const png = await fileOverCap("image/png");
    const fittedJpeg = await fitLinkedInImage(jpeg);
    const fittedPng = await fitLinkedInImage(png);
    return {
      jpegSource: jpeg.size,
      jpegBytes: atob(fittedJpeg.dataBase64).length,
      jpegType: fittedJpeg.contentType,
      pngSource: png.size,
      pngBytes: atob(fittedPng.dataBase64).length,
      pngType: fittedPng.contentType,
      corner: await corner(fittedPng.dataBase64),
    };
  });

  expect(result.jpegSource).toBeGreaterThan(1_500_000);
  expect(result.jpegBytes).toBeLessThanOrEqual(1_500_000);
  expect(result.jpegType).toBe("image/jpeg");
  expect(result.pngSource).toBeGreaterThan(1_500_000);
  expect(result.pngBytes).toBeLessThanOrEqual(1_500_000);
  expect(result.pngType).toBe("image/jpeg");
  expect(result.corner[0]).toBeGreaterThanOrEqual(240);
  expect(result.corner[1]).toBeGreaterThanOrEqual(240);
  expect(result.corner[2]).toBeGreaterThanOrEqual(240);
});

test("the draft file input stores that fitted JPEG", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "one Chromium canvas pass");
  test.setTimeout(90_000);
  await page.goto("/");
  const source = await page.evaluate(async () => {
    const canvas = document.createElement("canvas");
    canvas.width = 1400;
    canvas.height = 1400;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("no canvas");
    const data = context.createImageData(1400, 1400);
    for (let index = 0; index < data.data.length; index += 4) {
      const pixel = index / 4;
      const x = pixel % 1400;
      const y = Math.floor(pixel / 1400);
      const edge = x < 48 || y < 48;
      data.data[index] = (Math.random() * 255) | 0;
      data.data[index + 1] = (Math.random() * 255) | 0;
      data.data[index + 2] = (Math.random() * 255) | 0;
      data.data[index + 3] = edge ? 0 : 255;
    }
    context.putImageData(data, 0, 0);
    const blob = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob((value) => (value ? resolve(value) : reject(new Error("empty blob"))), "image/png");
    });
    const bytes = new Uint8Array(await blob.arrayBuffer());
    let binary = "";
    for (let index = 0; index < bytes.length; index += 0x8000) {
      binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
    }
    return { base64: btoa(binary), size: bytes.length };
  });
  expect(source.size).toBeGreaterThan(1_500_000);

  const path = join(tmpdir(), "linkedin-transparent.png");
  writeFileSync(path, Buffer.from(source.base64, "base64"));
  try {
    await page.goto("/lx-software?tab=linkedin&section=drafts&linkedin-post=li_hook");
    await page.locator("#linkedin-post-li_hook-image").setInputFiles(path);
    const img = page.getByRole("img", { name: "Draft picture" });
    await expect(img).toBeVisible();
    const sample = await img.evaluate((element: HTMLImageElement) => {
      const payload = element.src.split(",")[1] ?? "";
      const canvas = document.createElement("canvas");
      canvas.width = element.naturalWidth;
      canvas.height = element.naturalHeight;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("no canvas");
      context.drawImage(element, 0, 0);
      const pixel = context.getImageData(0, 0, 1, 1).data;
      return {
        bytes: atob(payload).length,
        jpeg: element.src.startsWith("data:image/jpeg"),
        corner: [pixel[0], pixel[1], pixel[2]],
      };
    });
    expect(sample.jpeg).toBe(true);
    expect(sample.bytes).toBeLessThanOrEqual(1_500_000);
    expect(sample.corner[0]).toBeGreaterThanOrEqual(240);
    expect(sample.corner[1]).toBeGreaterThanOrEqual(240);
    expect(sample.corner[2]).toBeGreaterThanOrEqual(240);
    await expect(page.getByText("A larger photo is resized to stay under 1.5 MB.")).toBeVisible();
    await img.scrollIntoViewIfNeeded();
    await page.screenshot({ path: "/opt/cursor/artifacts/draft-transparent-upload.png" });
  } finally {
    unlinkSync(path);
  }
});
