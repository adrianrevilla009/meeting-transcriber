import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Dashboard } from "./Dashboard";
import { meeting, mockApi, progress, renderApp, requirement } from "../test/utils";

const MEETINGS = [
  meeting({ id: 3, title: "Revisión sprint", project: "web", status: "finished", analysis_status: "pending" }),
  meeting({ id: 2, title: "Kickoff pagos", project: "pagos", status: "done", analysis_status: "pending" }),
  meeting({ id: 1, title: "", project: "pagos" }),
];

function setup(meetings = MEETINGS) {
  return mockApi({
    "GET /meetings": meetings,
    "GET /requirements": [requirement({ id: 1 }), requirement({ id: 2 })],
    "GET /meetings/3/progress": progress({ chunks_total: 4, chunks_done: 1 }),
    "GET /meetings/2/progress": progress(),
  });
}

describe("Dashboard", () => {
  it("shows stats and one card per meeting with its phase", async () => {
    setup();
    renderApp(<Dashboard />);
    const grid = await screen.findByText("Revisión sprint");
    expect(grid).toBeInTheDocument();
    const stat = (label: string) =>
      screen.getByText(label, { selector: ".stat .small" }).previousElementSibling?.textContent;
    expect(stat("Reuniones")).toBe("3");
    expect(stat("En proceso")).toBe("2");
    expect(stat("Requisitos")).toBe("2");
    expect(stat("Proyectos")).toBe("2");
    expect(screen.getByText("Reunión #1")).toBeInTheDocument(); // sin título
    expect(screen.getByText("Transcribiendo")).toBeInTheDocument();
    expect(screen.getByText("Analizando con IA")).toBeInTheDocument();
    expect(screen.getByText("Lista")).toBeInTheDocument();
  });

  it("shows transcription progress on busy cards", async () => {
    setup();
    renderApp(<Dashboard />);
    expect(await screen.findByText("1/4 fragmentos")).toBeInTheDocument();
    expect(screen.getByText(/La IA está leyendo/)).toBeInTheDocument();
  });

  it("filters by project chip and by title", async () => {
    setup();
    renderApp(<Dashboard />);
    await screen.findByText("Revisión sprint");
    const chips = screen.getByText("Todos").parentElement!;
    await userEvent.click(within(chips).getByText("#pagos"));
    expect(screen.queryByText("Revisión sprint")).not.toBeInTheDocument();
    expect(screen.getByText("Kickoff pagos")).toBeInTheDocument();

    await userEvent.click(within(chips).getByText("Todos"));
    await userEvent.type(screen.getByPlaceholderText("Filtrar por título"), "sprint");
    expect(screen.getByText("Revisión sprint")).toBeInTheDocument();
    expect(screen.queryByText("Kickoff pagos")).not.toBeInTheDocument();

    await userEvent.clear(screen.getByPlaceholderText("Filtrar por título"));
    await userEvent.type(screen.getByPlaceholderText("Filtrar por título"), "zzz");
    expect(screen.getByText("Sin resultados")).toBeInTheDocument();
  });

  it("cards link to the meeting page", async () => {
    setup();
    renderApp(<Dashboard />);
    await userEvent.click(await screen.findByText("Kickoff pagos"));
    expect(screen.getByTestId("location")).toHaveTextContent("/meetings/2");
  });

  it("empty state invites to record", async () => {
    setup([]);
    renderApp(<Dashboard />);
    expect(await screen.findByText("Aún no hay reuniones")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Grabar ahora/ }));
    expect(screen.getByTestId("location")).toHaveTextContent("/record");
  });

  it("shows API errors", async () => {
    mockApi({
      "GET /meetings": new Response(JSON.stringify({ detail: "BD caída" }), { status: 500 }),
      "GET /requirements": [],
    });
    renderApp(<Dashboard />);
    expect(await screen.findByText("BD caída")).toBeInTheDocument();
  });
});
