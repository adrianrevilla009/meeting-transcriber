import { describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfirmButton, highlight, KindBadge, ProgressBar, ProjectTag, StatusPill } from "./ui";

describe("StatusPill", () => {
  it.each([
    ["recording", "Grabando"],
    ["transcribing", "Transcribiendo"],
    ["analyzing", "Analizando con IA"],
    ["ready", "Lista"],
    ["failed", "Análisis fallido"],
  ] as const)("%s", (phase, label) => {
    render(<StatusPill phase={phase} />);
    expect(screen.getByText(label)).toHaveClass(`pill-${phase}`);
  });
});

it("KindBadge and ProjectTag", () => {
  const { container } = render(
    <>
      <KindBadge kind="open_question" />
      <ProjectTag name="pagos" />
      <ProjectTag name="" />
    </>,
  );
  expect(screen.getByText("Duda abierta")).toHaveClass("tone-sky");
  expect(screen.getByText("#pagos")).toBeInTheDocument();
  expect(container.querySelectorAll(".tag")).toHaveLength(1);
});

describe("ConfirmButton", () => {
  it("needs two clicks", async () => {
    const onConfirm = vi.fn();
    render(<ConfirmButton onConfirm={onConfirm}>Eliminar</ConfirmButton>);
    await userEvent.click(screen.getByRole("button", { name: "Eliminar" }));
    expect(onConfirm).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /Seguro/ }));
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Eliminar" })).toBeInTheDocument();
  });

  it("disarms itself after a few seconds", () => {
    vi.useFakeTimers();
    const onConfirm = vi.fn();
    render(<ConfirmButton onConfirm={onConfirm}>Eliminar</ConfirmButton>);
    act(() => screen.getByRole("button").click());
    expect(screen.getByRole("button")).toHaveTextContent(/Seguro/);
    act(() => vi.advanceTimersByTime(4100));
    expect(screen.getByRole("button")).toHaveTextContent("Eliminar");
    act(() => screen.getByRole("button").click());
    expect(onConfirm).not.toHaveBeenCalled();
    vi.useRealTimers();
  });
});

describe("highlight", () => {
  it("marks every case-insensitive match", () => {
    const { container } = render(<p>{highlight("Bizum y más BIZUM", "bizum")}</p>);
    expect(Array.from(container.querySelectorAll("mark")).map((m) => m.textContent)).toEqual(["Bizum", "BIZUM"]);
    expect(container.textContent).toBe("Bizum y más BIZUM");
  });

  it("treats regex characters literally", () => {
    const { container } = render(<p>{highlight("¿cuesta 5$ (o 6$)?", "(o 6$)")}</p>);
    expect(container.querySelector("mark")?.textContent).toBe("(o 6$)");
  });

  it("returns the text untouched for an empty needle", () => {
    expect(highlight("hola", "")).toBe("hola");
  });
});

it("ProgressBar clamps its value", () => {
  const { container } = render(
    <>
      <ProgressBar value={1.7} />
      <ProgressBar value={-1} />
      <ProgressBar value={0.25} indeterminate />
    </>,
  );
  const fills = container.querySelectorAll<HTMLElement>(".progress-fill");
  expect(Array.from(fills).map((f) => f.style.width)).toEqual(["100%", "0%", "25%"]);
  expect(container.querySelectorAll(".progress-indeterminate")).toHaveLength(1);
});
