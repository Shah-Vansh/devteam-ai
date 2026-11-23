import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useRunEvents } from "./useRunEvents";

/** A stand-in for the browser's EventSource that tests can push events into. */
class FakeEventSource {
  static last: FakeEventSource;
  listeners = new Map<string, ((e: MessageEvent<string>) => void)[]>();
  closed = false;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(readonly url: string) {
    FakeEventSource.last = this;
  }
  addEventListener(type: string, listener: (e: MessageEvent<string>) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }
  removeEventListener(type: string, listener: (e: MessageEvent<string>) => void) {
    this.listeners.set(type, (this.listeners.get(type) ?? []).filter((l) => l !== listener));
  }
  close() {
    this.closed = true;
  }
  emit(type: string, id: string, data: object) {
    const event = new MessageEvent<string>(type, { data: JSON.stringify(data), lastEventId: id });
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

beforeEach(() => {
  vi.stubGlobal("EventSource", FakeEventSource);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useRunEvents", () => {
  it("collects events, tells the caller, and closes after finished", () => {
    const seen: string[] = [];
    const { result } = renderHook(() => useRunEvents("run-1", (e) => seen.push(e.type)));
    const source = FakeEventSource.last;
    expect(source.url).toMatch(/\/api\/runs\/run-1\/events$/);

    act(() => {
      source.onopen?.();
      source.emit("log", "1", { message: "planner: planning" });
      source.emit("step", "2", { node: "plan" });
    });
    expect(result.current.connected).toBe(true);
    expect(result.current.events.map((e) => e.type)).toEqual(["log", "step"]);

    act(() => source.emit("finished", "3", { status: "SUCCESS" }));
    expect(result.current.finished).toBe(true);
    expect(result.current.connected).toBe(false);
    expect(source.closed).toBe(true);
    expect(seen).toEqual(["log", "step", "finished"]);
  });

  it("ignores events replayed after a reconnect", () => {
    const { result } = renderHook(() => useRunEvents("run-1"));
    const source = FakeEventSource.last;
    act(() => {
      source.emit("log", "1", { message: "a" });
      source.emit("log", "1", { message: "a" });
      source.emit("log", "2", { message: "b" });
    });
    expect(result.current.events.map((e) => e.data.message)).toEqual(["a", "b"]);
  });

  it("closes the stream when the screen goes away", () => {
    const { unmount } = renderHook(() => useRunEvents("run-1"));
    const source = FakeEventSource.last;
    unmount();
    expect(source.closed).toBe(true);
  });
});

it("shows when an event happened, not when a replay arrived", () => {
  const { result } = renderHook(() => useRunEvents("run-1"));
  act(() => FakeEventSource.last.emit("log", "1", { message: "a", at: "2026-11-23T11:41:47.000Z" }));
  expect(result.current.events[0]?.receivedAt.toISOString()).toBe("2026-11-23T11:41:47.000Z");
});
