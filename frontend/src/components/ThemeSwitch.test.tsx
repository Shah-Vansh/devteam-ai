import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ThemeSwitch } from "../App";
import { THEME_KEY } from "../hooks/useTheme";

function systemPrefersLight(light: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: light && query.includes("light"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

afterEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ThemeSwitch", () => {
  it("starts from the system setting when nothing is saved", () => {
    systemPrefersLight(true);
    render(<ThemeSwitch />);
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(screen.getByRole("button", { name: "Switch to dark theme" })).toBeInTheDocument();
  });

  it("a saved choice wins over the system setting", () => {
    systemPrefersLight(true);
    localStorage.setItem(THEME_KEY, "dark");
    render(<ThemeSwitch />);
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("switches the theme and remembers the choice", async () => {
    systemPrefersLight(false);
    render(<ThemeSwitch />);
    expect(document.documentElement.dataset.theme).toBe("dark");

    await userEvent.click(screen.getByRole("button", { name: "Switch to light theme" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem(THEME_KEY)).toBe("light");

    await userEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
  });

  it("still switches when storage is blocked", async () => {
    systemPrefersLight(false);
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    render(<ThemeSwitch />);
    await userEvent.click(screen.getByRole("button", { name: "Switch to light theme" }));
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
