import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  DEFAULT_LINKEDIN_SETTINGS,
  LINKEDIN_PILLARS,
  LINKEDIN_STORY_VOICES,
  RECOMMENDED_LINKEDIN_VOICE,
  type LinkedInOverview,
} from "../../lib/linkedinModel";
import { LinkedInSettingsCard } from "./LinkedInSettingsCard";

vi.mock("../../hooks/useLinkedIn", () => ({
  LINKEDIN_BYTES_KEY: ["linkedin-bytes"],
  useLinkedIn: () => ({
    saveSettings: { isPending: false, isError: false, error: null, mutateAsync: vi.fn() },
    connect: { isPending: false, error: null, mutateAsync: vi.fn() },
    disconnect: { isPending: false, error: null, mutate: vi.fn() },
    saveConnection: { error: null, mutate: vi.fn() },
    refreshOrganizations: { isPending: false, error: null, mutate: vi.fn() },
    character: { data: undefined },
    uploadCharacterPhoto: { error: null, mutate: vi.fn() },
    drawCharacter: { isPending: false, error: null, mutate: vi.fn() },
    chooseCharacter: { isPending: false, error: null, mutate: vi.fn() },
    deleteCharacterPhoto: { isPending: false, mutate: vi.fn() },
  }),
}));

function overview(voiceNotes: string): LinkedInOverview {
  return {
    enabled: true,
    publishEnabled: false,
    settings: { ...DEFAULT_LINKEDIN_SETTINGS, voiceNotes },
    pillars: LINKEDIN_PILLARS.map((row) => ({ id: row.id, label: row.label })),
    connection: {
      status: "not_connected",
      channel: "profile",
      memberName: "",
      organizationId: "",
      organizationName: "",
      organizations: [],
      tokenExpiresAt: "",
      includeOrganizations: false,
      appConfigured: true,
      appStatus: "ready",
    },
    counts: { drafted: 0, approved: 0, published: 0, ideas: 0 },
    spendUsdMonth: 0,
    nextSlots: [],
    builtinForbidden: [],
    defaultModel: "mistralai/mistral-medium-3",
    recommendedVoice: RECOMMENDED_LINKEDIN_VOICE,
    storyVoices: LINKEDIN_STORY_VOICES,
  };
}

describe("LinkedIn draft model hint", () => {
  it("says the Model field writes the scene, expression, and caption", () => {
    render(<LinkedInSettingsCard overview={overview("")} enabled />);
    expect(
      screen.getByText(/Writes each post and, when pictures are on, the scene, expression, and caption/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Leave blank for mistralai\/mistral-medium-3/)).toBeInTheDocument();
    expect(screen.getByText(/Draws the panel. Scene, expression, and caption use the Model field above/)).toBeInTheDocument();
  });
});

describe("LinkedIn story tones", () => {
  it("fills the Voice field from the tone button", async () => {
    const user = userEvent.setup();
    render(<LinkedInSettingsCard overview={overview("")} enabled />);

    const voice = screen.getByLabelText("Voice");
    expect(voice).toHaveValue("");
    expect(screen.getByRole("button", { name: "Over lunch" })).toHaveAttribute("aria-pressed", "false");

    await user.click(screen.getByRole("button", { name: "At the break" }));

    expect(voice).toHaveValue(LINKEDIN_STORY_VOICES[1]?.notes);
    expect(screen.getByRole("button", { name: "At the break" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Over lunch" })).toHaveAttribute("aria-pressed", "false");
  });

  it("marks Over lunch pressed when the field is the recommended voice", () => {
    render(<LinkedInSettingsCard overview={overview(RECOMMENDED_LINKEDIN_VOICE)} enabled />);
    expect(screen.getByRole("button", { name: "Over lunch" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: "Use recommended voice" })).toBeNull();
  });
});
