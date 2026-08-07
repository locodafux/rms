/* Color theme preference: stored per-browser, applied as data-theme on <html>;
   styles.css does the rest. Imported for its side effect in main.tsx, ahead of
   the first render, so the login screen (outside <Shell>) is themed too. */
export type Theme = "light" | "dark" | "system";

export const THEMES: Theme[] = ["system", "light", "dark"];

const mq = window.matchMedia("(prefers-color-scheme: dark)");

export function getTheme(): Theme {
  const t = localStorage.getItem("dt_theme");
  return THEMES.includes(t as Theme) ? (t as Theme) : "system";
}

export function applyTheme() {
  const t = getTheme();
  document.documentElement.dataset.theme =
    t === "system" ? (mq.matches ? "dark" : "light") : t;
}

export function setTheme(t: Theme) {
  localStorage.setItem("dt_theme", t);
  applyTheme();
}

mq.addEventListener("change", applyTheme); // keeps "System" live without a reload
applyTheme();
