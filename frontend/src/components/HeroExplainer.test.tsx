import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { Architecture, InputOutput } from "./HeroExplainer";

it("shows what you type and what you get", () => {
  render(<InputOutput />);
  const section = screen.getByRole("region", { name: "What you type and what you get" });
  expect(section).toHaveTextContent("Build a notes API with create, list and delete");
  expect(within(section).getByLabelText("Generated files")).toHaveTextContent("test_notes.py");
  // Words in the code snippet stay separated (JSX trims line breaks in markup).
  expect(within(section).getByLabelText("Part of app/main.py")).toHaveTextContent(
    'def create_note(note: NoteCreate): return store.add(note)',
  );
  expect(section).toHaveTextContent("8/8 tests passed · committed");
});

it("names every part of the architecture and who may write", () => {
  render(<Architecture />);
  const figure = screen.getByRole("figure", { name: "Architecture" });
  for (const part of ["Browser", "FastAPI", "LangGraph workflow", "Filesystem", "Git", "E2B"]) {
    expect(within(figure).getByText(part)).toBeInTheDocument();
  }
  expect(within(figure).getByLabelText(/agents: Planner, Developer, Reviewer, Tester/)).toBeVisible();
  expect(figure).toHaveTextContent("Agents only read");
});
