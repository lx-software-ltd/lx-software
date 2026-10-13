import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { DEFAULT_LINKEDIN_SETTINGS, SAMPLE_LINKEDIN_POSTS } from "../../lib/linkedinModel";
import { LinkedInDraftsSection } from "./LinkedInDraftsSection";

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
    uploadImage: { mutateAsync: vi.fn() },
    deleteImage: { mutate: vi.fn() },
  }),
}));

function renderDrafts() {
  return render(
    <MemoryRouter>
      <LinkedInDraftsSection settings={DEFAULT_LINKEDIN_SETTINGS} enabled />
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
