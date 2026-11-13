import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Record } from "./Record";
import { meeting, mockApi, renderApp } from "../test/utils";

function mediaDevices(overrides: Partial<MediaDevices>) {
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: overrides });
}

const orb = () => screen.getByRole("button", { name: /Empezar a grabar|Preparando/ });

describe("Record setup", () => {
  it("offers both sources on by default with sharing and headphone hints", async () => {
    mockApi({ "GET /meetings": [meeting({ project: "pagos" }), meeting({ id: 2, project: "web" })] });
    renderApp(<Record />);
    const toggles = screen.getAllByRole("button", { pressed: true });
    expect(toggles).toHaveLength(2);
    expect(screen.getByText(/Compartir audio del sistema/)).toBeInTheDocument();
    expect(screen.getByText(/Usa auriculares/)).toBeInTheDocument();
    await vi.waitFor(() => expect(document.querySelectorAll("#projects option")).toHaveLength(2));
  });

  it("cannot start with no sources", async () => {
    mockApi({ "GET /meetings": [] });
    renderApp(<Record />);
    await userEvent.click(screen.getByRole("button", { name: /Tu micrófono/ }));
    await userEvent.click(screen.getByRole("button", { name: /Audio del ordenador/ }));
    expect(orb()).toBeDisabled();
    expect(screen.queryByText(/Usa auriculares/)).not.toBeInTheDocument();
  });

  it("explains a denied microphone and does not create a meeting", async () => {
    const calls = mockApi({ "GET /meetings": [] });
    mediaDevices({ getUserMedia: vi.fn().mockRejectedValue(new DOMException("no", "NotAllowedError")) });
    renderApp(<Record />);
    await userEvent.click(screen.getByRole("button", { name: /Audio del ordenador/ }));
    await userEvent.click(orb());
    expect(await screen.findByText(/Permiso denegado/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("deletes the half-created meeting if audio setup fails afterwards", async () => {
    const track = { stop: vi.fn() };
    const calls = mockApi({ "GET /meetings": [], "POST /meetings": meeting({ id: 5, status: "recording" }), "DELETE /meetings/5": undefined });
    mediaDevices({ getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [track] }) });
    vi.stubGlobal("AudioContext", vi.fn(() => { throw new Error("Sin Web Audio"); })); // prettier-ignore
    renderApp(<Record />);
    await userEvent.type(screen.getByPlaceholderText("Kickoff con cliente"), "Demo");
    await userEvent.click(screen.getByRole("button", { name: /Audio del ordenador/ }));
    await userEvent.click(orb());
    expect(await screen.findByText("Sin Web Audio")).toBeInTheDocument();
    expect(calls.filter((c) => c.method !== "GET").map((c) => `${c.method} ${c.path}`)).toEqual(["POST /meetings", "DELETE /meetings/5"]);
    expect(JSON.parse(calls.find((c) => c.method === "POST")!.init.body as string)).toEqual({ title: "Demo", project: "" });
    expect(track.stop).toHaveBeenCalled(); // libera el micrófono
  });

  it("continues with the mic only when screen sharing is cancelled", async () => {
    mockApi({ "GET /meetings": [], "POST /meetings": meeting({ id: 6, status: "recording" }), "DELETE /meetings/6": undefined });
    const display = vi.fn().mockRejectedValue(new DOMException("cancel", "NotAllowedError"));
    mediaDevices({ getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [] }), getDisplayMedia: display });
    vi.stubGlobal("AudioContext", vi.fn(() => { throw new Error("parar aquí"); })); // prettier-ignore
    renderApp(<Record />);
    await userEvent.click(orb());
    expect(await screen.findByText("parar aquí")).toBeInTheDocument(); // llegó a crear el audio: no abortó por la pantalla
    expect(display).toHaveBeenCalledWith(expect.objectContaining({ systemAudio: "include" }));
  });
});
