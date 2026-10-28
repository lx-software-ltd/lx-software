import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AuthCallbackPage } from "./AuthCallbackPage";

vi.mock("../components/AuthProvider", () => ({
  useAuth: () => ({ refreshUser: () => undefined }),
}));

describe("AuthCallbackPage", () => {
  it("marks completing sign-in with a bao on the login canvas", () => {
    render(
      <MemoryRouter>
        <AuthCallbackPage />
      </MemoryRouter>,
    );
    const row = screen.getByRole("status");
    expect(row).toHaveTextContent("Completing sign-in…");
    expect(row.querySelector(".admin-bao")).toBeTruthy();
    expect(row.closest(".admin-login")).toBeTruthy();
  });
});
