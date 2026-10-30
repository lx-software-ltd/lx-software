import { afterEach, describe, expect, it, vi } from "vitest";
import { downloadBase64, openPreview } from "./downloadBase64";

describe("downloadBase64", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("keeps the object URL until the browser has started the download", () => {
    vi.useFakeTimers();
    const revoke = vi.fn();
    vi.stubGlobal("URL", {
      createObjectURL: () => "blob:resume",
      revokeObjectURL: revoke,
    });
    downloadBase64("resume.docx", "application/octet-stream", btoa("resume"));
    expect(revoke).not.toHaveBeenCalled();
    vi.advanceTimersByTime(60_000);
    expect(revoke).toHaveBeenCalledWith("blob:resume");
  });

  it("opens the preview window before any later await", () => {
    const popup = { opener: window } as Window;
    const open = vi.spyOn(window, "open").mockReturnValue(popup);
    expect(openPreview()).toBe(popup);
    expect(open).toHaveBeenCalledWith("about:blank", "_blank");
    expect(popup.opener).toBeNull();
    open.mockRestore();
  });
});
