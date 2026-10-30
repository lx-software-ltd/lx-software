import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import type { ResumeSummary } from "../../lib/resumeModel";
import { ResumeListSection } from "./ResumeListSection";

const sample: ResumeSummary = {
  id: "res_alex",
  title: "Alex Example",
  kind: "template",
  format: "docx",
  source: "upload",
  file: { contentType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", size: 12 },
  extract: { status: "ready", error: "" },
  derivedFrom: null,
  createdAt: "2026-10-30T02:00:00Z",
  updatedAt: "2026-10-30T02:00:00Z",
};

const { upload } = vi.hoisted(() => ({ upload: vi.fn() }));

vi.mock("../../hooks/useResume", () => ({
  useResume: () => ({
    resumes: { data: { items: [sample] }, isLoading: false },
    deleteResume: { isError: false, error: null, mutateAsync: vi.fn() },
    setTemplate: { isError: false, error: null, mutate: vi.fn(), isPending: false },
    patchResume: { isPending: false, isError: false, error: null, mutateAsync: vi.fn() },
    upload: { isPending: false, mutateAsync: upload },
  }),
  useResumeDetail: () => ({ data: undefined, isError: false, isLoading: false }),
  fetchResumeFile: vi.fn(),
}));

function renderList() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={["/lx-software?tab=resume&section=resumes"]}>
      <QueryClientProvider client={client}>
        <ResumeListSection enabled templateResumeId="res_alex" />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("Resume list", () => {
  it("marks the template and opens the upload row first", async () => {
    const user = userEvent.setup();
    const { container } = renderList();
    expect(screen.getByText("Alex Example")).toBeVisible();
    expect(screen.getAllByText("Template").length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "Add resume" }));
    expect(screen.getByLabelText("Title")).toHaveValue("");
    expect(screen.getByLabelText("Make this the template after it is read")).toBeChecked();
    expect(container.querySelector("tbody tbody")).toBeNull();
    const groups = container.querySelectorAll("table > tbody.admin-record-group");
    expect(groups).toHaveLength(2);
    expect(within(groups[0] as HTMLElement).getByText("Upload a resume")).toBeVisible();
    expect(screen.queryByText("New resume")).toBeNull();
  });

  it("closes the upload row and shows why a saved file could not be read", async () => {
    upload.mockResolvedValueOnce({
      resume: { ...sample, id: "res_new", title: "Contoso" },
      job: { jobId: "job_1", status: "failed", error: "No model is configured." },
    });
    const user = userEvent.setup();
    renderList();
    await user.click(screen.getByRole("button", { name: "Add resume" }));
    await user.type(screen.getByLabelText("Title"), "Contoso");
    await user.upload(screen.getByLabelText("File"), new File(["# Alex"], "alex.md", { type: "text/markdown" }));
    await user.click(screen.getByLabelText("Make this the template after it is read"));
    await user.click(screen.getByRole("button", { name: "Upload" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Contoso was saved but could not be read. No model is configured.",
    );
    expect(screen.queryByLabelText("Title")).toBeNull();
  });
});
