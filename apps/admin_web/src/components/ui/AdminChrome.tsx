/* eslint-disable react-refresh/only-export-components -- the rail slot shares its context */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

type AdminChromeValue = {
  readonly slot: HTMLElement | null;
  readonly setSlot: (node: HTMLElement | null) => void;
};

const AdminChromeContext = createContext<AdminChromeValue | null>(null);

export function AdminChromeProvider({ children }: { readonly children: ReactNode }) {
  const [slot, setSlotState] = useState<HTMLElement | null>(null);
  const setSlot = useCallback((node: HTMLElement | null) => {
    setSlotState(node);
  }, []);
  const value = useMemo(() => ({ slot, setSlot }), [slot, setSlot]);
  return <AdminChromeContext.Provider value={value}>{children}</AdminChromeContext.Provider>;
}

export function useAdminChrome(): AdminChromeValue {
  return useContext(AdminChromeContext) ?? { slot: null, setSlot: () => undefined };
}

/** Mounted under the active page link. Section tablists portal into this node. */
export function AdminRailSections() {
  const { setSlot } = useAdminChrome();
  const ref = useCallback(
    (node: HTMLDivElement | null) => {
      setSlot(node);
    },
    [setSlot],
  );
  return <div ref={ref} className="admin-rail-sections" />;
}
