import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  DEFAULT_LINKEDIN_SETTINGS,
  LINKEDIN_PILLARS,
  LINKEDIN_STORY_VOICES,
  RECOMMENDED_LINKEDIN_VOICE,
  type LinkedInOverview,
} from "../../lib/linkedinModel";
import { LinkedInSettingsCard } from "./LinkedInSettingsCard";

const { fitLinkedInImage, uploadCharacterPhoto } = vi.hoisted(() => ({
  fitLinkedInImage: vi.fn(async () => ({ contentType: "image/jpeg" as const, dataBase64: "c2hydW5r" })),
  uploadCharacterPhoto: { isPending: false, error: null as Error | null, mutate: vi.fn() },
}));

vi.mock("../../lib/fitLinkedInImage", () => ({
  fitLinkedInImage,
}));

vi.mock("../../hooks/useLinkedIn", () => ({
  LINKEDIN_BYTES_KEY: ["linkedin-bytes"],
  useLinkedIn: () => ({
    saveSettings: { isPending: false, isError: false, error: null, mutateAsync: vi.fn() },
    connect: { isPending: false, error: null, mutateAsync: vi.fn() },
    disconnect: { isPending: false, error: null, mutate: vi.fn() },
    saveConnection: { error: null, mutate: vi.fn() },
    refreshOrganizations: { isPending: false, error: null, mutate: vi.fn() },
    character: { data: undefined },
    uploadCharacterPhoto,
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
      includeMemberAnalytics: false,
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

describe("LinkedIn connection", () => {
  it("offers personal post analytics before connect", () => {
    render(<LinkedInSettingsCard overview={overview("")} enabled />);
    expect(screen.getByRole("checkbox", { name: "Include personal post analytics" })).not.toBeChecked();
    expect(screen.getByText(/including ones already published/)).toBeInTheDocument();
  });

  it("says existing posts are included once analytics is connected", () => {
    const connected = overview("");
    connected.connection = {
      ...connected.connection,
      status: "connected",
      memberName: "Example Member",
      includeMemberAnalytics: true,
    };
    render(<LinkedInSettingsCard overview={connected} enabled />);
    expect(screen.getByText(/including posts already published/)).toBeInTheDocument();
  });

  it("waits for LinkedIn approval when personal post analytics is off", () => {
    const connected = overview("");
    connected.connection = {
      ...connected.connection,
      status: "connected",
      memberName: "Example Member",
      includeMemberAnalytics: false,
    };
    render(<LinkedInSettingsCard overview={connected} enabled />);
    expect(screen.getByText(/approved for member post analytics/)).toBeInTheDocument();
    expect(screen.queryByText(/Disconnect and connect again with personal post analytics/)).toBeNull();
  });
});

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

describe("LinkedIn character photo", () => {
  beforeEach(() => {
    fitLinkedInImage.mockReset();
    fitLinkedInImage.mockResolvedValue({ contentType: "image/jpeg", dataBase64: "c2hydW5r" });
    uploadCharacterPhoto.mutate.mockReset();
    uploadCharacterPhoto.isPending = false;
    uploadCharacterPhoto.error = null;
  });

  it("resizes a photo over 1.5 MB and uploads the fitted JPEG", async () => {
    const user = userEvent.setup();
    let resolveFit: (value: { contentType: "image/jpeg"; dataBase64: string }) => void = () => {};
    fitLinkedInImage.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveFit = resolve;
        }),
    );
    render(<LinkedInSettingsCard overview={overview("")} enabled />);

    const input = screen.getByLabelText("Upload photo");
    expect(input).toHaveAttribute("accept", "image/png,image/jpeg,image/heic,image/heif");
    await user.upload(input, new File([new Uint8Array(1_600_000)], "large.png", { type: "image/png" }));

    expect(await screen.findByText("Resizing…")).toBeInTheDocument();
    expect(input).toBeDisabled();
    expect(uploadCharacterPhoto.mutate).not.toHaveBeenCalled();

    resolveFit({ contentType: "image/jpeg", dataBase64: "c2hydW5r" });
    await waitFor(() =>
      expect(uploadCharacterPhoto.mutate).toHaveBeenCalledWith({
        contentType: "image/jpeg",
        dataBase64: "c2hydW5r",
      }),
    );
  });

  it("labels the control Uploading… while the photo is saving", () => {
    uploadCharacterPhoto.isPending = true;
    render(<LinkedInSettingsCard overview={overview("")} enabled />);
    expect(screen.getByLabelText("Uploading…")).toBeDisabled();
  });
});
