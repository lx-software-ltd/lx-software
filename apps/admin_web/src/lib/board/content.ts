import type { BoardContentItem } from "./types";

/** Only a post the board itself published can be removed; hand-posted items carry "manual". */
export function canDeletePost(item: BoardContentItem): boolean {
  return item.status === "published" && Boolean(item.platformPostId) && item.platformPostId !== "manual";
}
