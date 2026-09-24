import { render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { useExpandedRecord } from "./useExpandedRecord";
import { useHydrateExpandedRecord } from "./useHydrateExpandedRecord";

function Editor({ recordsReady, records }: { recordsReady: boolean; records: readonly { id: string; name: string }[] }) {
  const expanded = useExpandedRecord("account");
  const [name, setName] = useState("");
  const record = records.find((row) => row.id === expanded.expandedId) ?? null;
  useHydrateExpandedRecord({
    expandedId: expanded.expandedId,
    recordsReady,
    record,
    apply: (row) => setName(row.name),
    onMissing: () => expanded.request(null, false),
  });
  return (
    <form>
      <label htmlFor="name">Description</label>
      <input id="name" value={name} onChange={(event) => setName(event.target.value)} />
      <button type="submit">{expanded.expandedId ? "Update record" : "Add record"}</button>
    </form>
  );
}

describe("useHydrateExpandedRecord", () => {
  afterEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("fills the editor from the deep-linked record before the user can save blanks", () => {
    window.history.replaceState(null, "", "/finance?account=ac-1");
    render(<Editor recordsReady records={[{ id: "ac-1", name: "HSBC HK current" }]} />);
    expect(screen.getByLabelText("Description")).toHaveProperty("value", "HSBC HK current");
  });

  it("clears an id that is not in the loaded list", () => {
    window.history.replaceState(null, "", "/finance?account=missing");
    render(<Editor recordsReady records={[{ id: "ac-1", name: "HSBC HK current" }]} />);
    expect(new URLSearchParams(window.location.search).get("account")).toBeNull();
    expect(screen.getByRole("button", { name: "Add record" })).toBeTruthy();
  });

  it("does not clear the id while the list is still loading", () => {
    window.history.replaceState(null, "", "/finance?account=ac-1");
    const { rerender } = render(<Editor recordsReady={false} records={[]} />);
    expect(new URLSearchParams(window.location.search).get("account")).toBe("ac-1");
    rerender(<Editor recordsReady records={[{ id: "ac-1", name: "HSBC HK current" }]} />);
    expect(screen.getByLabelText("Description")).toHaveProperty("value", "HSBC HK current");
  });
});
