import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Approval, ApprovalPayload } from "../api/types";
import { ApprovalPanel } from "./ApprovalPanel";

function approval(payload: ApprovalPayload): Approval {
  return {
    id: "apr_1",
    run_id: "run_1",
    kind: payload.kind,
    status: "pending",
    payload,
    answer: null,
    created_at: "2026-11-20T10:00:00Z",
    decided_at: null,
  };
}

const clarify = approval({ kind: "clarify", questions: ["Unique titles?", "Persist data?"] });
const execute = approval({ kind: "execute", executor: "e2b", workspace: "todo-1" });
const commit = approval({
  kind: "commit",
  workspace: "todo-1",
  files: ["app/main.py", "tests/test_a.py"],
  message: "Add todo-api\n\nA todo API.\n",
});

describe("ApprovalPanel", () => {
  it("sends the answers to the Planner's questions", async () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    render(<ApprovalPanel approval={clarify} onDecide={onDecide} />);
    await userEvent.type(screen.getByLabelText("Unique titles?"), "Yes, reject duplicates");
    await userEvent.click(screen.getByRole("button", { name: "Send answers" }));
    expect(onDecide).toHaveBeenCalledWith({
      decision: "approve",
      answers: ["Yes, reject duplicates", ""],
    });
  });

  it("can keep the Planner's assumptions", async () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    render(<ApprovalPanel approval={clarify} onDecide={onDecide} />);
    await userEvent.click(screen.getByRole("button", { name: "Keep assumptions" }));
    expect(onDecide).toHaveBeenCalledWith({ decision: "reject" });
  });

  it("asks before sending code to the sandbox", async () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    render(<ApprovalPanel approval={execute} onDecide={onDecide} />);
    expect(screen.getByText("e2b")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Run tests" }));
    expect(onDecide).toHaveBeenCalledWith({ decision: "approve" });
  });

  it("shows the files and lets the message be edited before committing", async () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    render(<ApprovalPanel approval={commit} onDecide={onDecide} />);
    expect(screen.getByText("tests/test_a.py")).toBeInTheDocument();
    const message = screen.getByLabelText("Commit message");
    await userEvent.clear(message);
    expect(screen.getByRole("button", { name: "Commit" })).toBeDisabled();
    await userEvent.type(message, "First version");
    await userEvent.click(screen.getByRole("button", { name: "Commit" }));
    expect(onDecide).toHaveBeenCalledWith({ decision: "approve", message: "First version" });
  });

  it("can cancel the whole run from any pause", async () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    render(<ApprovalPanel approval={commit} onDecide={onDecide} />);
    await userEvent.click(screen.getByRole("button", { name: "Cancel run" }));
    expect(onDecide).toHaveBeenCalledWith({ decision: "cancel" });
  });

  it("shows the error and lets the user try again", async () => {
    const onDecide = vi.fn().mockRejectedValue(new Error("run 1 is RUNNING"));
    render(<ApprovalPanel approval={execute} onDecide={onDecide} />);
    await userEvent.click(screen.getByRole("button", { name: "Run tests" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("run 1 is RUNNING");
    expect(screen.getByRole("button", { name: "Run tests" })).toBeEnabled();
  });
});
