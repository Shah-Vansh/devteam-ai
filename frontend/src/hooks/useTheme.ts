import { useCallback, useEffect, useState } from "react";

export type Theme = "dark" | "light";

export const THEME_KEY = "devteam-theme";

/** The saved choice, if the viewer picked one. Storage can be unavailable (private
 * windows, blocked site data), so every access is guarded. */
export function savedTheme(): Theme | undefined {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return value === "light" || value === "dark" ? value : undefined;
  } catch {
    return undefined;
  }
}

/** The operating system's preference. */
export function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
}

/** Current theme and a toggle. Starts from the saved choice, else the system setting
 * (index.html applies the same rule before the first paint), and follows system changes
 * until the viewer picks a theme themselves. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => savedTheme() ?? systemTheme());

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    const query = window.matchMedia?.("(prefers-color-scheme: light)");
    if (!query) return;
    const follow = () => {
      if (!savedTheme()) setTheme(query.matches ? "light" : "dark");
    };
    query.addEventListener?.("change", follow);
    return () => query.removeEventListener?.("change", follow);
  }, []);

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next: Theme = current === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(THEME_KEY, next);
      } catch {
        // not saved; the switch still works for this visit
      }
      return next;
    });
  }, []);

  return [theme, toggle];
}
