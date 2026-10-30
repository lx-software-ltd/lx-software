import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_RESUME_SETTINGS, LOCKED_FACTS, type ResumeOverview } from "../../lib/resumeModel";
import { ResumeSettingsCard } from "./ResumeSettingsCard";

const overview: ResumeOverview = {
  enabled: true,
  settings: DEFAULT_RESUME_SETTINGS,
  templateResumeId: "res_alex",
  defaultModel: "mistralai/mistral-medium-3",
  spendUsdMonth: 0.02,
  counts: { resumes: 1, postings: 1, applications: 1 },
  pdfCjk: false,
};

vi.mock("../../hooks/useResume", () => ({
  useResume: () => ({
    saveSettings: { isPending: false, isError: false, error: null, mutateAsync: vi.fn() },
  }),
}));

describe("Resume settings", () => {
  it("shows the model and the locked facts", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ResumeSettingsCard overview={overview} enabled />
      </QueryClientProvider>,
    );
    expect(screen.getByText(LOCKED_FACTS)).toBeVisible();
    expect(screen.getByLabelText("Model")).toHaveValue("");
    expect(screen.getByText(/Spent US\$ 0.02 of 5.00 this month/)).toBeVisible();
    expect(screen.getByText(/PDF export is Latin-only for now/)).toBeVisible();
  });

  it("asks for a rewrite scope before saving", async () => {
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ResumeSettingsCard overview={overview} enabled />
      </QueryClientProvider>,
    );
    for (const scope of ["headline", "summary", "bullets", "skills"]) {
      await user.click(screen.getByRole("checkbox", { name: scope }));
    }
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("at least one part of the resume");
  });
});
