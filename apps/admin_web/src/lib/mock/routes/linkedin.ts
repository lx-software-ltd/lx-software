import type { MockCtx } from "./types";
import { json, parseBody, state } from "./context";
import { isLinkedInPostUrl, nextSlots, type LinkedInPost } from "../../linkedinModel";

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
    connection: { status: "not_connected", channel: "profile" },
    counts: {
      drafted: posts.filter((row) => row.status === "drafted").length,
      approved: posts.filter((row) => row.status === "approved").length,
      published: posts.filter((row) => row.status === "published").length,
      ideas: state.linkedin.ideas.filter((row) => row.status === "new").length,
    },
    spendUsdMonth: 0,
    nextSlots: nextSlots(state.linkedin.settings, new Date(), 8, taken),
    builtinForbidden: ["lx software"],
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
    state.linkedin.settings = { ...state.linkedin.settings, ...parseBody(ctx.init) } as typeof state.linkedin.settings;
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
