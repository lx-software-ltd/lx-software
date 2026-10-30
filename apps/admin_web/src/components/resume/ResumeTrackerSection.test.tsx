import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import type { JobApplication } from "../../lib/resumeModel";
import { ResumeTrackerSection } from "./ResumeTrackerSection";

const application: JobApplication = {
  id: "app_northwind",
  resumeId: "res_alex",
  postingId: "post_northwind",
  company: "Northwind",
  position: "Engineer",
  recruiter: { name: "Morgan Example", email: "morgan.example@example.com", phone: "+1-555-0100" },
  status: "saved",
  appliedAt: "",
  nextStepAt: "",
  notes: "",
  createdAt: "2026-10-30T02:00:00Z",
  updatedAt: "2026-10-30T02:00:00Z",
};

const { saveApplication } = vi.hoisted(() => ({ saveApplication: vi.fn() }));

vi.mock("../../hooks/useResume", () => ({
  useResume: () => ({
    applications: { data: { items: [application] }, isLoading: false },
    resumes: { data: { items: [{ id: "res_alex", title: "Alex Example" }] }, isLoading: false },
    postings: {
      data: {
        items: [
          {
            id: "post_northwind",
            title: "Engineer",
            company: "Northwind",
            url: "",
            location: "",
            adText: "Billing export",
            createdAt: "2026-10-30T02:00:00Z",
          },
        ],
      },
      isLoading: false,
    },
    saveApplication: { isPending: false, isError: false, error: null, mutateAsync: saveApplication },
    deleteApplication: { isError: false, error: null, mutateAsync: vi.fn() },
  }),
}));

describe("Job tracker", () => {
  it("shows the recruiter on the open application", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <MemoryRouter initialEntries={["/?application=app_northwind"]}>
        <QueryClientProvider client={client}>
          <ResumeTrackerSection enabled />
        </QueryClientProvider>
      </MemoryRouter>,
    );
    expect(screen.getByText("Northwind")).toBeVisible();
    expect(screen.getByLabelText("Recruiter name")).toHaveValue("Morgan Example");
    expect(screen.getByLabelText("Recruiter email")).toHaveValue("morgan.example@example.com");
    expect(screen.getByLabelText("Recruiter phone")).toHaveValue("+1-555-0100");
    expect(screen.getByLabelText("Job post")).toHaveValue("post_northwind");
    expect(screen.getByLabelText("Applied")).toHaveAttribute("type", "date");
  });

  it("closes a new application after it is saved", async () => {
    saveApplication.mockResolvedValue({ item: { ...application, id: "app_new" } });
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <MemoryRouter>
        <QueryClientProvider client={client}>
          <ResumeTrackerSection enabled />
        </QueryClientProvider>
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: "Add application" }));
    await user.type(screen.getByLabelText("Company"), "Contoso");
    await user.type(screen.getByLabelText("Position"), "Analyst");
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(saveApplication).toHaveBeenCalled();
    expect(screen.queryByLabelText("Company")).not.toBeInTheDocument();
  });
});
