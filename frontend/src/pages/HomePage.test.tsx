import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";
import { NewProjectForm } from "./HomePage";

afterEach(() => {
  vi.restoreAllMocks();
});

async function fillForm() {
  await userEvent.type(screen.getByLabelText("Name"), "todo");
  await userEvent.type(screen.getByLabelText("Requirement"), "Build a todo API");
}

describe("NewProjectForm", () => {
  it("creates the project, starts a run and hands over the run id", async () => {
    const create = vi.spyOn(api, "createProject").mockResolvedValue({
      id: "prj_1",
      name: "todo",
      requirement: "Build a todo API",
      created_at: "",
    });
    const start = vi.spyOn(api, "startRun").mockResolvedValue({ run_id: "run-1", status: "RUNNING" });
    const onStarted = vi.fn();
    render(<NewProjectForm onStarted={onStarted} />);

    expect(screen.getByRole("button", { name: "Create and start" })).toBeDisabled();
    await fillForm();
    await userEvent.click(screen.getByRole("button", { name: "Create and start" }));

    expect(create).toHaveBeenCalledWith("todo", "Build a todo API");
    expect(start).toHaveBeenCalledWith("prj_1");
    expect(onStarted).toHaveBeenCalledWith("run-1");
  });

  it("shows the API's message when starting fails", async () => {
    vi.spyOn(api, "createProject").mockResolvedValue({
      id: "prj_1",
      name: "todo",
      requirement: "x",
      created_at: "",
    });
    vi.spyOn(api, "startRun").mockRejectedValue(
      new ApiError(503, "LLM_NOT_CONFIGURED", "LLM_API_KEY is not set in the root .env"),
    );
    render(<NewProjectForm onStarted={vi.fn()} />);
    await fillForm();
    await userEvent.click(screen.getByRole("button", { name: "Create and start" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("LLM_API_KEY is not set");
  });

  it("only offers FastAPI projects", () => {
    render(<NewProjectForm onStarted={vi.fn()} />);
    expect(screen.getByLabelText("Project type")).toBeDisabled();
  });
});
