import type { MockCtx } from "./types";
import { json, parseBody, state } from "./context";
import {
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
    state.linkedin.settings = {
      ...state.linkedin.settings,
      ...body,
      voiceNotes: voice,
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
  if (path.endsWith("/image") && method === "POST" && index >= 0) {
    const body = parseBody(ctx.init);
    const contentType = String(body.contentType ?? "");
    if (contentType !== "image/png" && contentType !== "image/jpeg") {
      return json({ message: "Use a PNG or JPEG image." }, 400);
    }
    state.linkedin.posts[index] = { ...state.linkedin.posts[index], image: { contentType } };
    return json({ item: state.linkedin.posts[index] });
  }
  if (path.endsWith("/image") && method === "DELETE" && index >= 0) {
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
