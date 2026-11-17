import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { SAMPLE_LINKEDIN_POSTS, type LinkedInPost } from "../../lib/linkedinModel";
import { LinkedInPublishedSection } from "./LinkedInPublishedSection";

const { postedItems } = vi.hoisted(() => ({
  postedItems: { current: null as LinkedInPost[] | null },
}));

vi.mock("../../hooks/useLinkedIn", () => ({
  useLinkedIn: () => ({
    posts: { data: { items: postedItems.current ?? SAMPLE_LINKEDIN_POSTS }, isLoading: false },
  }),
}));

function renderPosted() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <LinkedInPublishedSection />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("LinkedIn posted reach", () => {
  afterEach(() => {
    postedItems.current = null;
  });

  it("groups impression thousands with a comma", () => {
    renderPosted();
    expect(screen.getByText("4 reactions · 1 comments · 30,000 impressions")).toBeInTheDocument();
    expect(screen.queryByText(/30000 impressions/)).toBeNull();
  });

  it("groups every reach figure", () => {
    postedItems.current = [
      {
        ...SAMPLE_LINKEDIN_POSTS[1],
        postId: "li_big",
        metrics: { reactions: 1200, comments: 3400, impressions: 26498 },
      },
    ];
    renderPosted();
    expect(screen.getByText("1,200 reactions · 3,400 comments · 26,498 impressions")).toBeInTheDocument();
  });

  it("omits impressions when they are missing", () => {
    postedItems.current = [
      {
        ...SAMPLE_LINKEDIN_POSTS[1],
        postId: "li_no_impressions",
        metrics: { reactions: 4, comments: 1, impressions: null },
      },
    ];
    renderPosted();
    expect(screen.getByText("4 reactions · 1 comments")).toBeInTheDocument();
    expect(screen.queryByText(/impressions/)).toBeNull();
  });

  it("omits reactions that were never read", () => {
    postedItems.current = [
      {
        ...SAMPLE_LINKEDIN_POSTS[1],
        postId: "li_impressions_only",
        metrics: { impressions: 26498, reactions: null, comments: null },
      },
    ];
    renderPosted();
    expect(screen.getByText("26,498 impressions")).toBeInTheDocument();
    expect(screen.queryByText(/reactions/)).toBeNull();
  });
});
