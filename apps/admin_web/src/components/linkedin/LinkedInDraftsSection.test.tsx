import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { DEFAULT_LINKEDIN_SETTINGS, IMAGE_SCENE_MAX, SAMPLE_LINKEDIN_POSTS } from "../../lib/linkedinModel";
import { LinkedInDraftsSection } from "./LinkedInDraftsSection";

const { fitLinkedInImage, uploadImage } = vi.hoisted(() => ({
  fitLinkedInImage: vi.fn(async () => ({ contentType: "image/jpeg" as const, dataBase64: "c2hydW5r" })),
  uploadImage: { isPending: false, mutateAsync: vi.fn() },
}));

vi.mock("../../lib/fitLinkedInImage", () => ({
  fitLinkedInImage,
}));

const updatePost = { isPending: false, error: null, mutate: vi.fn(), mutateAsync: vi.fn() };
const starPost = { isPending: false, error: null, mutate: vi.fn(), mutateAsync: vi.fn() };

vi.mock("../../hooks/useLinkedIn", () => ({
  LINKEDIN_BYTES_KEY: ["linkedin-bytes"],
  useLinkedIn: () => ({
    posts: { data: { items: SAMPLE_LINKEDIN_POSTS }, isLoading: false },
    generate: { isPending: false, isError: false, error: null },
    updatePost,
    starPost,
    act: { isPending: false, error: null, mutate: vi.fn(), mutateAsync: vi.fn() },
    createPost: { isPending: false, error: null, mutateAsync: vi.fn() },
    regenerate: { mutate: vi.fn() },
    redrawImage: { isPending: false, mutate: vi.fn(), mutateAsync: vi.fn() },
    rewriteBrief: { isPending: false, mutateAsync: vi.fn() },
    uploadImage,
    deleteImage: { mutate: vi.fn() },
  }),
}));

function renderDrafts(path = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={[path]}>
      <QueryClientProvider client={client}>
        <LinkedInDraftsSection
          settings={DEFAULT_LINKEDIN_SETTINGS}
          enabled
          defaultModel="mistralai/mistral-medium-3"
        />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("LinkedIn draft stars", () => {
  it("stars a draft without opening the editor", async () => {
    const user = userEvent.setup();
    renderDrafts();

    const star = screen.getByRole("button", { name: "Star draft" });
    expect(star).toHaveAttribute("aria-pressed", "false");
    expect(star).not.toHaveClass("is-on");

    await user.click(star);

    expect(starPost.mutate).toHaveBeenCalledWith({ postId: "li_hook", starred: true });
    expect(screen.queryByLabelText("Post")).toBeNull();
  });
});

describe("LinkedIn new post", () => {
  it("opens the new post editor at the top of the table", async () => {
    const user = userEvent.setup();
    renderDrafts();

    await user.click(screen.getByRole("button", { name: "New post" }));

    const editor = screen.getByLabelText("Post");
    const firstDraft = screen.getByText("A rollback is a design decision.");
    expect(editor.compareDocumentPosition(firstDraft) & Node.DOCUMENT_POSITION_FOLLOWING).toBeGreaterThan(0);
  });
});

describe("LinkedIn draft scene", () => {
  it("allows a scene three times the old 400-character cap", () => {
    renderDrafts("/?linkedin-post=li_hook");
    expect(screen.getByLabelText("Scene")).toHaveAttribute("maxLength", String(IMAGE_SCENE_MAX));
    expect(IMAGE_SCENE_MAX).toBe(1200);
  });

  it("names the draft model that writes the scene, expression, and caption", () => {
    renderDrafts("/?linkedin-post=li_hook");
    expect(screen.getByText(/by mistralai\/mistral-medium-3/)).toBeInTheDocument();
  });
});

describe("LinkedIn draft image upload", () => {
  beforeEach(() => {
    fitLinkedInImage.mockReset();
    fitLinkedInImage.mockResolvedValue({ contentType: "image/jpeg", dataBase64: "c2hydW5r" });
    uploadImage.mutateAsync.mockReset();
    uploadImage.isPending = false;
  });

  it("resizes a JPEG over 1.5 MB and still uploads it", async () => {
    const user = userEvent.setup();
    uploadImage.mutateAsync.mockResolvedValue({});
    renderDrafts("/?linkedin-post=li_hook");

    const bytes = new Uint8Array(1_600_000);
    bytes[0] = 0xff;
    bytes[1] = 0xd8;
    bytes[2] = 0xff;
    const file = new File([bytes], "large.jpg", { type: "image/jpeg" });
    await user.upload(screen.getByLabelText("Picture"), file);

    expect(screen.queryByText("The image must be under 1.5 MB.")).toBeNull();
    await waitFor(() =>
      expect(uploadImage.mutateAsync).toHaveBeenCalledWith({
        postId: "li_hook",
        contentType: "image/jpeg",
        dataBase64: "c2hydW5r",
      }),
    );
  });

  it("shows Resizing… and blocks another pick until the photo is fitted", async () => {
    const user = userEvent.setup();
    let resolveFit: (value: { contentType: "image/jpeg"; dataBase64: string }) => void = () => {};
    fitLinkedInImage.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveFit = resolve;
        }),
    );
    uploadImage.mutateAsync.mockResolvedValue({});
    renderDrafts("/?linkedin-post=li_hook");

    const input = screen.getByLabelText("Picture");
    expect(input).toHaveAttribute("accept", "image/png,image/jpeg,image/heic,image/heif");
    await user.upload(input, new File([new Uint8Array([1])], "large.jpg", { type: "image/jpeg" }));

    expect(await screen.findByText("Resizing…")).toBeInTheDocument();
    expect(input).toBeDisabled();
    expect(uploadImage.mutateAsync).not.toHaveBeenCalled();

    resolveFit({ contentType: "image/jpeg", dataBase64: "c2hydW5r" });
    await waitFor(() => expect(uploadImage.mutateAsync).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText("Resizing…")).toBeNull());
    expect(input).toBeEnabled();
  });

  it("disables the file input while the upload is in flight", () => {
    uploadImage.isPending = true;
    renderDrafts("/?linkedin-post=li_hook");
    expect(screen.getByLabelText("Picture")).toBeDisabled();
    expect(screen.getByText("Uploading…")).toBeInTheDocument();
  });
});
