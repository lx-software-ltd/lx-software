import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ResumeTailorSection } from "./ResumeTailorSection";

vi.mock("../../hooks/useResume", () => ({
  useResume: () => ({
    resumes: {
      data: {
        items: [
          {
            id: "res_alex",
            title: "Alex Example",
            format: "docx",
            extract: { status: "ready", error: "" },
          },
        ],
      },
    },
    postings: { data: { items: [] } },
    upload: { isPending: false, mutateAsync: vi.fn() },
    tailor: { isPending: false, mutateAsync: vi.fn() },
  }),
}));

describe("New resume", () => {
  it("starts blank and follows the template once it is known", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = render(
      <QueryClientProvider client={client}>
        <ResumeTailorSection enabled templateResumeId="" onOpenResume={() => undefined} />
      </QueryClientProvider>,
    );
    expect(screen.getByLabelText("Title")).toHaveValue("");
    view.rerender(
      <QueryClientProvider client={client}>
        <ResumeTailorSection enabled templateResumeId="res_alex" onOpenResume={() => undefined} />
      </QueryClientProvider>,
    );
    expect(screen.getByLabelText("Word template")).toHaveValue("res_alex");
    expect(screen.getByLabelText("Company")).toHaveValue("");
    expect(screen.getByLabelText("Position")).toHaveValue("");
    expect(screen.getByLabelText("Job post")).toHaveValue("");
  });
});
