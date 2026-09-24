/* eslint-disable react-refresh/only-export-components -- theme hooks stay with the provider */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type ThemeMode = "light" | "dark" | "system";
export type Density = "compact" | "comfortable";

const THEME_KEY = "admin-theme";
const DENSITY_KEY = "admin-density";

type ThemeContextValue = {
  readonly theme: ThemeMode;
  readonly density: Density;
  readonly setTheme: (mode: ThemeMode) => void;
  readonly cycleTheme: () => void;
  readonly toggleDensity: () => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readTheme(): ThemeMode {
  const stored = localStorage.getItem(THEME_KEY);
  if (stored === "light" || stored === "dark" || stored === "system") return stored;
  return "system";
}

function readDensity(): Density {
  return localStorage.getItem(DENSITY_KEY) === "comfortable" ? "comfortable" : "compact";
}

function applyTheme(mode: ThemeMode): void {
  const dark =
    mode === "dark" ||
    (mode === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.bsTheme = dark ? "dark" : "light";
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
}

function applyDensity(density: Density): void {
  document.documentElement.dataset.density = density;
}

export function ThemeProvider({ children }: { readonly children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeMode>(readTheme);
  const [density, setDensity] = useState<Density>(readDensity);

  useEffect(() => {
    applyTheme(theme);
    localStorage.setItem(THEME_KEY, theme);
    if (theme !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [theme]);

  useEffect(() => {
    applyDensity(density);
    localStorage.setItem(DENSITY_KEY, density);
  }, [density]);

  const setTheme = useCallback((mode: ThemeMode) => setThemeState(mode), []);
  const cycleTheme = useCallback(() => {
    setThemeState((current) =>
      current === "system" ? "light" : current === "light" ? "dark" : "system",
    );
  }, []);
  const toggleDensity = useCallback(() => {
    setDensity((current) => (current === "compact" ? "comfortable" : "compact"));
  }, []);

  const value = useMemo(
    () => ({ theme, density, setTheme, cycleTheme, toggleDensity }),
    [theme, density, setTheme, cycleTheme, toggleDensity],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme must be used within ThemeProvider");
  return value;
}

const THEME_LABEL: Record<ThemeMode, string> = {
  system: "Theme: system",
  light: "Theme: light",
  dark: "Theme: dark",
};

const THEME_ICON: Record<ThemeMode, string> = {
  system: "bi-circle-half",
  light: "bi-sun",
  dark: "bi-moon",
};

export function ThemeControls() {
  const { theme, density, cycleTheme, toggleDensity } = useTheme();
  return (
    <div className="admin-theme-controls">
      <button type="button" className="admin-rail-tool" onClick={cycleTheme} aria-label={THEME_LABEL[theme]}>
        <i className={`bi ${THEME_ICON[theme]}`} aria-hidden="true" />
        <span className="admin-nav-label">{THEME_LABEL[theme]}</span>
      </button>
      <button
        type="button"
        className="admin-rail-tool"
        onClick={toggleDensity}
        aria-label={density === "compact" ? "Density: compact" : "Density: comfortable"}
      >
        <i className="bi bi-distribute-vertical" aria-hidden="true" />
        <span className="admin-nav-label">{density === "compact" ? "Compact rows" : "Comfortable rows"}</span>
      </button>
    </div>
  );
}
