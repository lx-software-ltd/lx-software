import type { MockCtx } from "./types";
import { json, parseBody, state } from "./context";
import {
  DEFAULT_IMAGE_MODEL,
  IMAGE_MODEL_ALTERNATIVE,
  RECOMMENDED_IMAGE_STYLE,
  RECOMMENDED_LINKEDIN_VOICE,
  STYLE_EXAMPLE_MAX,
  isLinkedInPostUrl,
  nextSlots,
  type LinkedInConnection,
  type LinkedInPost,
} from "../../linkedinModel";

const DISCONNECTED: LinkedInConnection = {
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
};

const EXAMPLE_PAGE = { id: "99", name: "Example Page" };
const OAUTH_KEY = "lx-mock-linkedin-oauth";
const OAUTH_PAGES_KEY = "lx-mock-linkedin-oauth-pages";

function rememberOauth(token: string, includeOrganizations: boolean) {
  state.linkedin.oauthState = token;
  sessionStorage.setItem(OAUTH_KEY, token);
  sessionStorage.setItem(OAUTH_PAGES_KEY, includeOrganizations ? "1" : "0");
}

function readOauth(): string {
  return state.linkedin.oauthState || sessionStorage.getItem(OAUTH_KEY) || "";
}

function readOauthPages(): boolean {
  return sessionStorage.getItem(OAUTH_PAGES_KEY) === "1";
}

function overview() {
  const posts = state.linkedin.posts;
  const taken = new Set(
    posts.filter((row) => row.status === "approved" || row.status === "published").map((row) => row.slotAt),
  );
  return {
    enabled: true,
    publishEnabled: false,
    settings: state.linkedin.settings,
    pillars: [
      { id: "architecture", label: "Architecture decisions" },
      { id: "leadership", label: "Engineering leadership" },
      { id: "platforms", label: "Cloud and platforms" },
      { id: "ai-practice", label: "AI in practice" },
      { id: "delivery", label: "Lessons from delivery" },
      { id: "questions", label: "Questions I get asked" },
    ],
    connection: state.linkedin.connection,
    counts: {
      drafted: posts.filter((row) => row.status === "drafted").length,
      approved: posts.filter((row) => row.status === "approved").length,
      published: posts.filter((row) => row.status === "published").length,
      ideas: state.linkedin.ideas.filter((row) => row.status === "new").length,
    },
    spendUsdMonth: 0,
    nextSlots: nextSlots(state.linkedin.settings, new Date(), 8, taken),
    builtinForbidden: ["lx software"],
    defaultModel: "mistralai/mistral-medium-3",
    recommendedVoice: RECOMMENDED_LINKEDIN_VOICE,
    styleExampleMax: STYLE_EXAMPLE_MAX,
    defaultImageModel: DEFAULT_IMAGE_MODEL,
    imageModelAlternative: IMAGE_MODEL_ALTERNATIVE,
    recommendedImageStyle: RECOMMENDED_IMAGE_STYLE,
    imageStyleMax: 600,
    imageCharacterMax: 400,
  };
}

const MOCK_PNG = "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";
const MOCK_PNG_REDRAW = "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";

function publicCharacter() {
  const character = state.linkedin.character;
  return {
    photo: character.photo ? { contentType: character.photo.contentType } : null,
    sheet: character.sheet ? { contentType: character.sheet.contentType } : null,
    candidates: character.candidates.map((row) => ({ id: row.id, contentType: row.contentType })),
  };
}

function postIdFrom(path: string): string {
  const parts = path.split("/").filter(Boolean);
  return parts[3] ?? "";
}

export function handleLinkedIn(ctx: MockCtx): Response | null {
  const { path, method } = ctx;
  if (path !== "/lx-software/linkedin" && !path.startsWith("/lx-software/linkedin/")) return null;
  if (path === "/lx-software/linkedin" && method === "GET") return json(overview());
  if (path === "/lx-software/linkedin/settings" && method === "PUT") {
    const body = parseBody(ctx.init);
    const voice = String(body.voiceNotes ?? state.linkedin.settings.voiceNotes).trim();
    const example = String(body.styleExample ?? state.linkedin.settings.styleExample).trim();
    state.linkedin.settings = {
      ...state.linkedin.settings,
      ...body,
      voiceNotes: voice,
      styleExample: example,
    } as typeof state.linkedin.settings;
    return json({ settings: state.linkedin.settings });
  }
  if (path === "/lx-software/linkedin/posts" && method === "GET") {
    return json({ items: state.linkedin.posts.filter((row) => row.status !== "archived") });
  }
  if (path === "/lx-software/linkedin/posts" && method === "POST") {
    const body = parseBody(ctx.init);
    const post: LinkedInPost = {
      postId: `li_${state.linkedin.posts.length + 1}`,
      status: "drafted",
      channel: "profile",
      pillar: String(body.pillar ?? "architecture"),
      ideaId: "",
      body: String(body.body ?? ""),
      firstComment: String(body.firstComment ?? ""),
      hashtags: Array.isArray(body.hashtags) ? body.hashtags.map(String) : [],
      slotAt: "",
      guardrails: [],
    };
    state.linkedin.posts = [post, ...state.linkedin.posts];
    return json({ item: post }, 201);
  }
  if (path === "/lx-software/linkedin/ideas" && method === "GET") {
    return json({ items: state.linkedin.ideas });
  }
  if (path === "/lx-software/linkedin/ideas" && method === "POST") {
    const body = parseBody(ctx.init);
    const idea = {
      ideaId: `idea_${state.linkedin.ideas.length + 1}`,
      text: String(body.text ?? ""),
      pillar: String(body.pillar ?? ""),
      status: "new",
      usedBy: "",
    };
    state.linkedin.ideas = [idea, ...state.linkedin.ideas];
    return json({ item: idea }, 201);
  }
  if (path.startsWith("/lx-software/linkedin/ideas/") && method === "DELETE") {
    const ideaId = path.split("/").pop() ?? "";
    state.linkedin.ideas = state.linkedin.ideas.filter((row) => row.ideaId !== ideaId);
    return json({ deleted: ideaId });
  }
  if (path === "/lx-software/linkedin/connect" && method === "POST") {
    const body = parseBody(ctx.init);
    const includeOrganizations = Boolean(body.includeOrganizations);
    const token = `oauth_${state.linkedin.posts.length}`;
    rememberOauth(token, includeOrganizations);
    return json({ url: `/lx-software/linkedin/callback?code=mock&state=${encodeURIComponent(token)}` });
  }
  if (path === "/lx-software/linkedin/oauth/exchange" && method === "POST") {
    const body = parseBody(ctx.init);
    if (!readOauth() || body.state !== readOauth()) {
      return json({ message: "That LinkedIn sign-in expired. Connect again." }, 400);
    }
    const includeOrganizations = readOauthPages();
    state.linkedin.oauthState = "";
    sessionStorage.removeItem(OAUTH_KEY);
    sessionStorage.removeItem(OAUTH_PAGES_KEY);
    state.linkedin.connection = {
      status: "connected",
      channel: "profile",
      memberName: "Example Member",
      organizationId: "",
      organizationName: "",
      organizations: includeOrganizations ? [EXAMPLE_PAGE] : [],
      tokenExpiresAt: "2099-01-01T00:00:00.000Z",
      includeOrganizations,
      appConfigured: true,
      appStatus: "ready",
    };
    return json({ connection: state.linkedin.connection });
  }
  if (path === "/lx-software/linkedin/disconnect" && method === "POST") {
    state.linkedin.connection = { ...DISCONNECTED, organizations: [] };
    return json({ connection: state.linkedin.connection });
  }
  if (path === "/lx-software/linkedin/connection/refresh" && method === "POST") {
    if (state.linkedin.connection.status !== "connected") {
      return json({ message: "LinkedIn is not connected." }, 400);
    }
    if (!state.linkedin.connection.includeOrganizations) {
      return json(
        { message: "This connection is profile only. Disconnect and connect again with company pages included." },
        400,
      );
    }
    state.linkedin.connection = {
      ...state.linkedin.connection,
      organizations: [EXAMPLE_PAGE],
    };
    return json({ connection: state.linkedin.connection });
  }
  if (path === "/lx-software/linkedin/connection" && method === "PUT") {
    if (state.linkedin.connection.status !== "connected") {
      return json({ message: "LinkedIn is not connected." }, 400);
    }
    const body = parseBody(ctx.init);
    const channel = String(body.channel ?? "profile");
    if (channel === "page") {
      const organizationId = String(body.organizationId ?? "");
      const page = state.linkedin.connection.organizations.find((row) => row.id === organizationId);
      if (!page) return json({ message: "Choose a company page you administer." }, 400);
      state.linkedin.connection = {
        ...state.linkedin.connection,
        channel: "page",
        organizationId: page.id,
        organizationName: page.name,
      };
    } else {
      state.linkedin.connection = { ...state.linkedin.connection, channel: "profile" };
    }
    return json({ connection: state.linkedin.connection });
  }
  if (path === "/lx-software/linkedin/generate" && method === "POST") {
    const post: LinkedInPost = {
      postId: `li_gen_${state.linkedin.posts.length + 1}`,
      status: "drafted",
      channel: "profile",
      pillar: "leadership",
      ideaId: "",
      body: "A generated hook.\n\nThis stands in for the model in mock mode.",
      firstComment: "",
      hashtags: [],
      slotAt: "",
      guardrails: [],
    };
    state.linkedin.posts = [post, ...state.linkedin.posts];
    return json({ job: { jobId: "job_mock", status: "done", postIds: [post.postId], error: "" } }, 202);
  }
  const id = postIdFrom(path);
  const index = state.linkedin.posts.findIndex((row) => row.postId === id);
  if (path === "/lx-software/linkedin/character" && method === "GET") return json(publicCharacter());
  if (path === "/lx-software/linkedin/character/photo" && method === "POST") {
    const body = parseBody(ctx.init);
    const contentType = String(body.contentType ?? "");
    if (contentType !== "image/png" && contentType !== "image/jpeg") {
      return json({ message: "Use a PNG or JPEG image." }, 400);
    }
    state.linkedin.character.photo = { contentType, dataBase64: String(body.dataBase64 ?? "") };
    return json(publicCharacter());
  }
  if (path === "/lx-software/linkedin/character/photo" && method === "GET") {
    const photo = state.linkedin.character.photo;
    if (!photo) return json({ message: "No photo stored." }, 404);
    return json(photo);
  }
  if (path === "/lx-software/linkedin/character/photo" && method === "DELETE") {
    state.linkedin.character.photo = null;
    return json(publicCharacter());
  }
  if (path === "/lx-software/linkedin/character/sheet" && method === "GET") {
    const sheet = state.linkedin.character.sheet;
    if (!sheet) return json({ message: "No character sheet yet." }, 404);
    return json(sheet);
  }
  if (path === "/lx-software/linkedin/character/draw" && method === "POST") {
    if (!state.linkedin.character.photo) return json({ message: "Upload a photo first." }, 400);
    state.linkedin.character.candidates = ["c1", "c2", "c3", "c4"].map((id) => ({
      id,
      contentType: "image/png",
      dataBase64: MOCK_PNG,
    }));
    return json({ job: { jobId: "job_character", status: "done", postIds: [], error: "" } }, 202);
  }
  if (path.startsWith("/lx-software/linkedin/character/candidates/") && method === "GET") {
    const id = path.split("/").pop() ?? "";
    const row = state.linkedin.character.candidates.find((item) => item.id === id);
    if (!row) return json({ message: "That candidate is gone." }, 404);
    return json({ contentType: row.contentType, dataBase64: row.dataBase64 });
  }
  if (path === "/lx-software/linkedin/character/choose" && method === "POST") {
    const id = String(parseBody(ctx.init).candidateId ?? "");
    const row = state.linkedin.character.candidates.find((item) => item.id === id);
    if (!row) return json({ message: "That candidate is gone. Draw the character again." }, 400);
    state.linkedin.character.sheet = { contentType: row.contentType, dataBase64: row.dataBase64 };
    return json(publicCharacter());
  }
  if (path.endsWith("/image/regenerate") && method === "POST" && index >= 0) {
    const body = parseBody(ctx.init);
    const current = state.linkedin.posts[index].image;
    if (current?.status === "pending") return json({ message: "A picture is already being drawn." }, 409);
    state.linkedin.images[id] = { contentType: "image/png", dataBase64: MOCK_PNG_REDRAW };
    state.linkedin.posts[index] = {
      ...state.linkedin.posts[index],
      image: {
        status: "ready",
        contentType: "image/png",
        scene: String(body.scene ?? current?.scene ?? "The author at a desk."),
        caption: String(body.caption ?? current?.caption ?? "This took longer than I expected."),
        error: "",
        model: "bytedance-seed/seedream-4.5",
      },
    };
    return json({ item: state.linkedin.posts[index] }, 202);
  }
  if (path.endsWith("/image") && method === "GET" && index >= 0) {
    const stored = state.linkedin.images[id];
    if (stored) return json(stored);
    const image = state.linkedin.posts[index].image;
    if (image?.contentType) return json({ contentType: "image/png", dataBase64: MOCK_PNG });
    return json({ message: "No picture stored." }, 404);
  }
  if (path.endsWith("/image") && method === "POST" && index >= 0) {
    const body = parseBody(ctx.init);
    const contentType = String(body.contentType ?? "");
    if (contentType !== "image/png" && contentType !== "image/jpeg") {
      return json({ message: "Use a PNG or JPEG image." }, 400);
    }
    state.linkedin.images[id] = { contentType, dataBase64: String(body.dataBase64 ?? "") };
    state.linkedin.posts[index] = {
      ...state.linkedin.posts[index],
      image: { contentType, status: "ready", scene: "", caption: "", error: "", model: "" },
    };
    return json({ item: state.linkedin.posts[index] });
  }
  if (path.endsWith("/image") && method === "DELETE" && index >= 0) {
    delete state.linkedin.images[id];
    state.linkedin.posts[index] = { ...state.linkedin.posts[index], image: null };
    return json({ item: state.linkedin.posts[index] });
  }
  if (index < 0 && path.includes("/posts/")) return json({ message: "post not found" }, 404);
  if (path.endsWith("/approve") && method === "POST" && index >= 0) {
    const slot = nextSlots(state.linkedin.settings, new Date(), 1)[0] ?? "";
    state.linkedin.posts[index] = { ...state.linkedin.posts[index], status: "approved", slotAt: slot };
    return json({ item: state.linkedin.posts[index] });
  }
  if (path.endsWith("/unapprove") && method === "POST" && index >= 0) {
    state.linkedin.posts[index] = { ...state.linkedin.posts[index], status: "drafted", slotAt: "" };
    return json({ item: state.linkedin.posts[index] });
  }
  if (path.endsWith("/archive") && method === "POST" && index >= 0) {
    state.linkedin.posts[index] = { ...state.linkedin.posts[index], status: "archived" };
    return json({ item: state.linkedin.posts[index] });
  }
  if (path.endsWith("/mark-posted") && method === "POST" && index >= 0) {
    const url = String(parseBody(ctx.init).url ?? "");
    if (!isLinkedInPostUrl(url)) return json({ message: "Paste the linkedin.com URL of the live post." }, 400);
    state.linkedin.posts[index] = {
      ...state.linkedin.posts[index],
      status: "published",
      platform: { url, publishedAt: new Date().toISOString() },
    };
    return json({ item: state.linkedin.posts[index] });
  }
  if (path.endsWith("/regenerate") && method === "POST" && index >= 0) {
    state.linkedin.posts[index] = {
      ...state.linkedin.posts[index],
      status: "drafted",
      slotAt: "",
      body: "A regenerated hook.\n\nSame idea, new wording.",
    };
    return json({ job: { jobId: "job_regen", status: "done", postIds: [id], error: "" } }, 202);
  }
  if (method === "PUT" && path === `/lx-software/linkedin/posts/${id}` && index >= 0) {
    const body = parseBody(ctx.init);
    state.linkedin.posts[index] = {
      ...state.linkedin.posts[index],
      body: String(body.body ?? state.linkedin.posts[index].body),
      firstComment: String(body.firstComment ?? state.linkedin.posts[index].firstComment),
      pillar: String(body.pillar ?? state.linkedin.posts[index].pillar),
      hashtags: Array.isArray(body.hashtags) ? body.hashtags.map(String) : state.linkedin.posts[index].hashtags,
    };
    return json({ item: state.linkedin.posts[index] });
  }
  return json({ message: `Mock API has no route for ${path}` }, 404);
}
