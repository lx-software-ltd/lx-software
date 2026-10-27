import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter, MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AdminApiError, adminFetchJson } from "../lib/apiAdminClient";
import { AssetsPage } from "./AssetsPage";

vi.mock("../lib/apiAdminClient", async () => {
  const actual = await vi.importActual<typeof import("../lib/apiAdminClient")>(
    "../lib/apiAdminClient",
  );
  return { ...actual, adminFetchJson: vi.fn() };
});

const fetchJson = vi.mocked(adminFetchJson);

const firstPageRow = {
  pk: "ASSET#uploads/admin-sub/one.pdf",
  sk: "META",
  fileName: "one.pdf",
  uploadedAt: "2026-01-02T00:00:00.000Z",
  size: 10,
  house: "hillmarton",
};

function renderPage(path = "/assets") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router =
    path === "/assets" ? (
      <MemoryRouter initialEntries={[path]}>
        <AssetsPage />
      </MemoryRouter>
    ) : (
      <BrowserRouter>
        <AssetsPage />
      </BrowserRouter>
    );
  return render(<QueryClientProvider client={client}>{router}</QueryClientProvider>);
}

describe("AssetsPage", () => {
  beforeEach(() => {
    fetchJson.mockReset();
  });

  afterEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("loads one page and fetches the next only after Load more", async () => {
    fetchJson.mockImplementation(async (path: string) => {
      if (path === "/assets") return { items: [firstPageRow], nextCursor: "cursor-2" };
      if (path.startsWith("/assets?cursor=")) {
        return {
          items: [
            {
              ...firstPageRow,
              pk: "ASSET#uploads/admin-sub/two.pdf",
              fileName: "two.pdf",
              uploadedAt: "2026-01-01T00:00:00.000Z",
            },
          ],
          nextCursor: null,
        };
      }
      throw new Error(path);
    });
    renderPage();
    expect(await screen.findByText("one.pdf")).toBeTruthy();
    expect(screen.queryByText("two.pdf")).toBeNull();
    expect(fetchJson).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("two.pdf")).toBeTruthy();
    expect(fetchJson).toHaveBeenCalledTimes(2);
  });

  it("opens a deep-linked asset from its object key", async () => {
    const objectKey = "uploads/admin-sub/one.pdf";
    window.history.replaceState(null, "", `/assets?asset=${encodeURIComponent(objectKey)}`);
    fetchJson.mockResolvedValue({ items: [firstPageRow], nextCursor: null });
    renderPage(window.location.pathname + window.location.search);
    expect(await screen.findByLabelText("Object key")).toHaveProperty("value", objectKey);
    expect(fetchJson.mock.calls.some((call) => String(call[0]).includes("key="))).toBe(false);
  });

  it("shows a deep-linked asset that is not on the loaded page", async () => {
    const objectKey = "uploads/admin-sub/linked.pdf";
    window.history.replaceState(null, "", `/assets?asset=${encodeURIComponent(objectKey)}`);
    fetchJson.mockImplementation(async (path: string) => {
      if (path === "/assets") return { items: [firstPageRow], nextCursor: null };
      if (path.startsWith("/assets?key=")) {
        return {
          item: {
            ...firstPageRow,
            pk: `ASSET#${objectKey}`,
            fileName: "linked.pdf",
          },
        };
      }
      throw new Error(path);
    });
    renderPage(window.location.pathname + window.location.search);
    expect(await screen.findByLabelText("Object key")).toHaveProperty("value", objectKey);
    expect(fetchJson.mock.calls.some((call) => String(call[0]).includes("key="))).toBe(true);
  });

  it("clears a deep link when that asset does not exist", async () => {
    const pk = "ASSET#uploads/admin-sub/missing.pdf";
    window.history.replaceState(null, "", `/assets?asset=${encodeURIComponent(pk)}`);
    fetchJson.mockImplementation(async (path: string) => {
      if (path === "/assets") return { items: [], nextCursor: null };
      if (path.startsWith("/assets?key=")) {
        throw new AdminApiError(404, JSON.stringify({ message: "Asset not found" }));
      }
      throw new Error(path);
    });
    renderPage(window.location.pathname + window.location.search);
    expect(await screen.findByText("No confirmed assets yet.")).toBeTruthy();
    await waitFor(() => {
      expect(new URLSearchParams(window.location.search).get("asset")).toBeNull();
    });
  });
});
