import { afterEach, describe, expect, it, vi } from "vitest";
import { API_BASE_URL, ApiError, api } from "./client";

function respond(status: number, body: unknown) {
  return vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api client", () => {
  it("returns the parsed body on success", async () => {
    const fetchMock = respond(201, { id: "prj_1", name: "todo" });
    vi.stubGlobal("fetch", fetchMock);
    const project = await api.createProject("todo", "Build a todo API");
    expect(project.id).toBe("prj_1");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}/api/projects`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ name: "todo", requirement: "Build a todo API" });
  });

  it("turns the API's error shape into an ApiError with its code", async () => {
    vi.stubGlobal(
      "fetch",
      respond(409, {
        error: { code: "RUN_ALREADY_ACTIVE", message: "already active", details: { run_id: "r1" } },
      }),
    );
    const error = await api.startRun("prj_1").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 409,
      code: "RUN_ALREADY_ACTIVE",
      message: "already active",
      details: { run_id: "r1" },
    });
  });

  it("reports an unreachable backend clearly", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(api.health()).rejects.toMatchObject({ code: "NETWORK_ERROR", status: 0 });
  });

  it("encodes ids and file paths in URLs", async () => {
    const fetchMock = respond(200, { path: "a b.py", content: "" });
    vi.stubGlobal("fetch", fetchMock);
    await api.fileContent("run/1", "../a b.py");
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe(`${API_BASE_URL}/api/runs/run%2F1/files/content?path=..%2Fa%20b.py`);
  });
});
