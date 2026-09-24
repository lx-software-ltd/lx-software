import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useExpandedRecord } from "./useExpandedRecord";

describe("useExpandedRecord", () => {
  afterEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("opens a row and writes its id into the query string", () => {
    const { result } = renderHook(() => useExpandedRecord("account"));
    act(() => result.current.request("row-1", false));
    expect(result.current.expandedId).toBe("row-1");
    expect(new URLSearchParams(window.location.search).get("account")).toBe("row-1");
  });

  it("asks before replacing a dirty open row", () => {
    const { result } = renderHook(() => useExpandedRecord("account"));
    act(() => result.current.request("row-1", false));
    act(() => result.current.request("row-2", true));
    expect(result.current.expandedId).toBe("row-1");
    expect(result.current.confirmOpen).toBe(true);
    act(() => result.current.acceptPending());
    expect(result.current.expandedId).toBe("row-2");
    expect(result.current.confirmOpen).toBe(false);
  });

  it("keeps the open row when the discard is cancelled", () => {
    const { result } = renderHook(() => useExpandedRecord("account"));
    act(() => result.current.request("row-1", false));
    act(() => result.current.request(null, true));
    act(() => result.current.cancelPending());
    expect(result.current.expandedId).toBe("row-1");
    expect(result.current.confirmOpen).toBe(false);
  });

  it("toggles the same row closed", () => {
    const { result } = renderHook(() => useExpandedRecord("line"));
    act(() => result.current.toggle("row-1", false, () => undefined, () => undefined));
    expect(result.current.expandedId).toBe("row-1");
    act(() => result.current.toggle("row-1", false, () => undefined, () => undefined));
    expect(result.current.expandedId).toBeNull();
    expect(new URLSearchParams(window.location.search).get("line")).toBeNull();
  });
});
