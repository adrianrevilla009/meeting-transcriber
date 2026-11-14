import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Login } from "./Login";
import { mockApi } from "../test/utils";

describe("Login", () => {
  it("is disabled until a token is typed", async () => {
    render(<Login onLogin={vi.fn()} />);
    const btn = screen.getByRole("button", { name: /Entrar/ });
    expect(btn).toBeDisabled();
    await userEvent.type(screen.getByPlaceholderText(/MT_API_TOKEN/), "   ");
    expect(btn).toBeDisabled();
  });

  it("validates the token against the API and trims it", async () => {
    const calls = mockApi({ "GET /meetings": [] });
    const onLogin = vi.fn();
    render(<Login onLogin={onLogin} />);
    await userEvent.type(screen.getByPlaceholderText(/MT_API_TOKEN/), "  secreto  {Enter}");
    await vi.waitFor(() => expect(onLogin).toHaveBeenCalledWith("secreto"));
    expect(new Headers(calls[0].init.headers).get("Authorization")).toBe("Bearer secreto");
  });

  it("shows an error for a wrong token", async () => {
    mockApi({ "GET /meetings": new Response("{}", { status: 401 }) });
    const onLogin = vi.fn();
    render(<Login onLogin={onLogin} />);
    await userEvent.type(screen.getByPlaceholderText(/MT_API_TOKEN/), "mal");
    await userEvent.click(screen.getByRole("button", { name: /Entrar/ }));
    expect(await screen.findByText("Ese token no es válido.")).toBeInTheDocument();
    expect(onLogin).not.toHaveBeenCalled();
  });

  it("explains when the API is down", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    render(<Login onLogin={vi.fn()} />);
    await userEvent.type(screen.getByPlaceholderText(/MT_API_TOKEN/), "x{Enter}");
    expect(await screen.findByText(/make start/)).toBeInTheDocument();
  });
});
