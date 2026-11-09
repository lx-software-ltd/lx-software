import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { canDeletePost, type BoardContentItem } from "../../lib/boardModel";
import { ContentDrawer } from "./BoardContentSection";

const published: BoardContentItem = {
  contentId: "cnt-fb",
  status: "published",
  channel: "facebook",
  pillar: "neighbourhood",
  slotAt: "2026-11-06T02:00:00Z",
  copyZh: "赤柱",
  platformPostId: "122111322747512744",
};

function renderDrawer(item: BoardContentItem, onDeletePost = vi.fn()) {
  render(
    <ContentDrawer
      item={item}
      error={null}
      onClose={vi.fn()}
      onSave={vi.fn()}
      onRender={vi.fn()}
      onDeletePost={onDeletePost}
    />,
  );
  return onDeletePost;
}

describe("canDeletePost", () => {
  it("is true only for a post the board published", () => {
    expect(canDeletePost(published)).toBe(true);
    expect(canDeletePost({ ...published, status: "scheduled" })).toBe(false);
    expect(canDeletePost({ ...published, platformPostId: "manual" })).toBe(false);
    expect(canDeletePost({ ...published, platformPostId: undefined })).toBe(false);
  });
});

describe("ContentDrawer delete post", () => {
  it("hides the button for scheduled items", () => {
    renderDrawer({ ...published, status: "scheduled", platformPostId: undefined });
    expect(screen.queryByRole("button", { name: "Delete post" })).toBeNull();
  });

  it("asks for confirmation before deleting a Facebook post", () => {
    const onDeletePost = renderDrawer(published);
    expect(screen.getByText(/post 122111322747512744/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Delete post" }));
    expect(onDeletePost).not.toHaveBeenCalled();
    expect(screen.getByText(/Removes the post from the Facebook Page/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Confirm delete" }));
    expect(onDeletePost).toHaveBeenCalledTimes(1);
  });

  it("explains that Instagram posts cannot be deleted through the API", () => {
    const onDeletePost = renderDrawer({ ...published, channel: "instagram", platformPostId: "ig-1" });
    fireEvent.click(screen.getByRole("button", { name: "Delete post" }));
    expect(screen.getByText(/Instagram does not allow deleting/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Confirm delete" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Delete post" })).toBeTruthy();
    expect(onDeletePost).not.toHaveBeenCalled();
  });

  it("shows the removed post id after deletion", () => {
    renderDrawer({ ...published, status: "vetoed", platformPostId: "", deletedPostId: "122111322747512744" });
    expect(screen.getByText(/deleted post 122111322747512744/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Delete post" })).toBeNull();
  });
});
