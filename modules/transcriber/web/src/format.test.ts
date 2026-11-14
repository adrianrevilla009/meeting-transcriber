import { afterEach, describe, expect, it, vi } from "vitest";
import { fmtDuration, fmtRelative, fmtTs, isBusy, meetingTitle, phaseOf, slug } from "./format";
import { meeting } from "./test/utils";

describe("fmtTs", () => {
  it.each([
    [0, "00:00"],
    [9.9, "00:09"],
    [65, "01:05"],
    [3600, "1:00:00"],
    [3725, "1:02:05"],
    [-4, "00:00"],
    [null, "00:00"],
  ])("%s → %s", (secs, out) => expect(fmtTs(secs)).toBe(out));
});

describe("phaseOf", () => {
  it.each([
    [{ status: "recording" }, "recording"],
    [{ status: "finished" }, "transcribing"],
    [{ status: "done", analysis_status: "pending" }, "analyzing"],
    [{ status: "done", analysis_status: "failed" }, "failed"],
    [{ status: "done", analysis_status: "done" }, "ready"],
    [{ status: "done", analysis_status: "skipped" }, "ready"],
  ] as const)("%o → %s", (patch, phase) => expect(phaseOf(meeting(patch))).toBe(phase));

  it("only transcribing and analyzing count as busy", () => {
    expect(["recording", "transcribing", "analyzing", "ready", "failed"].filter((p) => isBusy(p as never))).toEqual([
      "transcribing",
      "analyzing",
    ]);
  });
});

describe("fmtDuration", () => {
  it("formats minutes and hours", () => {
    expect(fmtDuration("2026-01-01T10:00:00Z", "2026-01-01T10:42:00Z")).toBe("42 min");
    expect(fmtDuration("2026-01-01T10:00:00Z", "2026-01-01T11:05:00Z")).toBe("1 h 5 min");
    expect(fmtDuration("2026-01-01T10:00:00Z", "2026-01-01T10:00:20Z")).toBe("< 1 min");
    expect(fmtDuration("2026-01-01T10:00:00Z", null)).toBeNull();
  });
});

describe("fmtRelative", () => {
  afterEach(() => vi.useRealTimers());
  it("uses human relative times", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-13T12:00:00Z"));
    expect(fmtRelative("2026-11-13T11:59:30Z")).toBe("ahora mismo");
    expect(fmtRelative("2026-11-13T11:55:00Z")).toBe("hace 5 minutos");
    expect(fmtRelative("2026-11-13T09:00:00Z")).toBe("hace 3 horas");
    expect(fmtRelative("2026-11-12T12:00:00Z")).toBe("ayer");
  });
});

describe("slug / meetingTitle", () => {
  it("makes safe file names", () => {
    expect(slug("Reunión de Diseño: ¡v2!")).toBe("reunion-de-diseno-v2");
    expect(slug("···")).toBe("reunion");
  });
  it("falls back to the id when untitled", () => {
    expect(meetingTitle({ id: 7, title: "  " })).toBe("Reunión #7");
    expect(meetingTitle({ id: 7, title: "Kickoff" })).toBe("Kickoff");
  });
});
