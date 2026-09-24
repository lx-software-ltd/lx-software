import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AdminCell } from "./AdminDataTable";
import { AdminExpandableRow } from "./AdminExpandableRow";
import { AdminRowActions } from "./AdminRowActions";
import { ConfirmDialog } from "./ConfirmDialog";

describe("AdminExpandableRow", () => {
  it("shows the editor only while the row is open", () => {
    const { rerender } = render(
      <table>
        <AdminExpandableRow colSpan={2} expanded={false} onToggle={() => undefined} editor={<p>Editor</p>}>
          <AdminCell column="name">Alpha</AdminCell>
          <AdminCell column="ops">Ops</AdminCell>
        </AdminExpandableRow>
      </table>,
    );
    expect(screen.queryByText("Editor")).toBeNull();
    rerender(
      <table>
        <AdminExpandableRow colSpan={2} expanded onToggle={() => undefined} editor={<p>Editor</p>}>
          <AdminCell column="name">Alpha</AdminCell>
          <AdminCell column="ops">Ops</AdminCell>
        </AdminExpandableRow>
      </table>,
    );
    expect(screen.getByText("Editor")).toBeTruthy();
  });

  it("does not toggle when the editor is clicked", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    render(
      <table>
        <AdminExpandableRow colSpan={1} expanded onToggle={onToggle} editor={<button type="button">Inside</button>}>
          <td>Alpha</td>
        </AdminExpandableRow>
      </table>,
    );
    await user.click(screen.getByRole("button", { name: "Inside" }));
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("toggles from the keyboard and ignores a text selection", () => {
    const onToggle = vi.fn();
    render(
      <table>
        <AdminExpandableRow colSpan={1} expanded={false} onToggle={onToggle} editor={<p>Editor</p>}>
          <td>Alpha</td>
        </AdminExpandableRow>
      </table>,
    );
    const row = screen.getByRole("row");
    fireEvent.keyDown(row, { key: "Enter" });
    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(row.getAttribute("aria-expanded")).toBe("false");
    vi.spyOn(window, "getSelection").mockReturnValue({
      isCollapsed: false,
      toString: () => "Alpha",
    } as Selection);
    fireEvent.click(row);
    expect(onToggle).toHaveBeenCalledTimes(1);
    vi.restoreAllMocks();
  });
});

describe("AdminRowActions", () => {
  it("puts the third action in the more menu", () => {
    render(
      <AdminRowActions
        actions={[
          { id: "edit", label: "Edit record", iconClassName: "bi bi-pencil", onClick: () => undefined },
          { id: "copy", label: "Duplicate record", iconClassName: "bi bi-copy", onClick: () => undefined },
          { id: "delete", label: "Delete record", iconClassName: "bi bi-trash", onClick: () => undefined },
        ]}
      />,
    );
    expect(screen.queryByRole("button", { name: "Edit record" })).toBeNull();
    expect(screen.getByRole("button", { name: "More actions" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Edit record", hidden: true })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Delete record", hidden: true })).toBeTruthy();
  });

  it("closes the menu before running an overflow action", () => {
    const onDelete = vi.fn();
    const hidePopover = vi.fn();
    HTMLElement.prototype.hidePopover = hidePopover;
    render(
      <AdminRowActions
        actions={[
          { id: "edit", label: "Edit record", iconClassName: "bi bi-pencil", onClick: () => undefined },
          { id: "copy", label: "Duplicate record", iconClassName: "bi bi-copy", onClick: () => undefined },
          { id: "delete", label: "Delete record", iconClassName: "bi bi-trash", onClick: onDelete },
        ]}
      />,
    );
    const item = screen.getByRole("button", { name: "Delete record", hidden: true });
    vi.spyOn(item.closest("[popover]") as HTMLElement, "matches").mockImplementation(
      (selectors) => selectors === ":popover-open",
    );
    fireEvent.click(item);
    expect(hidePopover).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledTimes(1);
  });
});

describe("ConfirmDialog", () => {
  it("confirms and cancels", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
      this.open = true;
    };
    HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
      this.open = false;
    };
    render(
      <ConfirmDialog
        open
        title="Delete account"
        body="Delete this account record?"
        confirmLabel="Delete"
        tone="danger"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(onConfirm).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
