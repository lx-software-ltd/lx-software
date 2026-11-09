import type { MockCtx } from "./types";
import { json, state } from "./context";

const CONTENT_PREFIX = "/siu-tin-dei/board/content/";
const SUFFIX = "/delete-post";

/** Owner-only delete of a published Facebook post; mirrors board_content.delete_post. */
export function handleContentDeletePost(ctx: MockCtx): Response | null {
  const p = ctx.path;
  if (!(ctx.method === "POST" && p.startsWith(CONTENT_PREFIX) && p.endsWith(SUFFIX))) return null;
  const contentId = decodeURIComponent(p.slice(CONTENT_PREFIX.length, -SUFFIX.length));
  const idx = state.content.findIndex((row) => row.contentId === contentId);
  if (idx < 0) return json({ message: "Content not found" }, 404);
  const row = state.content[idx];
  if (row.status !== "published" || !row.platformPostId || row.platformPostId === "manual") {
    return json({ message: "only a post the board published can be deleted" }, 400);
  }
  if (row.channel !== "facebook") {
    return json({ message: "Instagram does not allow deleting posts through the API; delete it in the app, then veto this item" }, 400);
  }
  state.content[idx] = { ...row, status: "vetoed", platformPostId: "", deletedPostId: row.platformPostId };
  return json({ item: state.content[idx] });
}
