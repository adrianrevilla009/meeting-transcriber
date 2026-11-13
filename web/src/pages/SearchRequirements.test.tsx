import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Search } from "./Search";
import { Requirements } from "./Requirements";
import { event, meeting, mockApi, renderApp, requirement } from "../test/utils";

describe("Search page", () => {
  const routes = {
    "GET /meetings": [meeting({ id: 1, title: "Kickoff" }), meeting({ id: 2, title: "Revisión" })],
    "GET /search": ({ url }: { url: URL }) =>
      url.searchParams.get("q") === "bizum"
        ? [
            { meeting_id: 2, segment_id: 20, start: 65, text: "Ahora también Bizum" },
            { meeting_id: 1, segment_id: 10, start: 3, text: "Pagar con Bizum" },
            { meeting_id: 2, segment_id: 21, start: 90, text: "Bizum otra vez" },
          ]
        : [],
  };

  it("asks for at least two letters without calling the API", async () => {
    const calls = mockApi(routes);
    renderApp(<Search />);
    await userEvent.type(screen.getByPlaceholderText(/presupuesto/), "b");
    expect(await screen.findByText("Escribe al menos 2 letras")).toBeInTheDocument();
    expect(calls.filter((c) => c.path.startsWith("/search"))).toHaveLength(0);
  });

  it("groups results by meeting, highlights and links to the sentence", async () => {
    mockApi(routes);
    renderApp(<Search />);
    await userEvent.type(screen.getByPlaceholderText(/presupuesto/), "bizum");
    expect(await screen.findByText("3 coincidencias en 2 reuniones")).toBeInTheDocument();
    const groups = document.querySelectorAll(".search-group");
    expect(within(groups[0] as HTMLElement).getByText("Revisión")).toBeInTheDocument();
    expect(groups[0].querySelectorAll(".search-hit")).toHaveLength(2);
    expect(document.querySelectorAll("mark")).toHaveLength(3);
    expect(within(groups[0] as HTMLElement).getByText("01:05")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Pagar con", { exact: false }));
    expect(screen.getByTestId("location")).toHaveTextContent("/meetings/1?seg=10");
  });

  it("explains when nothing matches", async () => {
    mockApi(routes);
    renderApp(<Search />);
    await userEvent.type(screen.getByPlaceholderText(/presupuesto/), "kubernetes");
    expect(await screen.findByText("Sin coincidencias")).toBeInTheDocument();
  });
});

describe("Requirements page", () => {
  const routes = {
    "GET /meetings": [meeting({ id: 1, title: "Kickoff" }), meeting({ id: 2, title: "Revisión" })],
    "GET /requirements": [
      requirement({ id: 1, title: "Método de pago", project: "pagos" }),
      requirement({ id: 2, title: "Modo oscuro", project: "web" }),
    ],
    "GET /requirements/1/history": {
      requirement: requirement({ id: 1, title: "Método de pago", project: "pagos" }),
      events: [
        event({
          id: 1,
          meeting_id: 1,
          kind: "new_requirement",
          summary: "Solo tarjeta",
          quote: "solo con tarjeta",
          segment_id: 5,
        }),
        event({
          id: 2,
          meeting_id: 2,
          kind: "changed_requirement",
          summary: "Se añade Bizum",
          quote: "también Bizum",
          segment_id: 9,
        }),
      ],
    },
    "GET /requirements/2/history": {
      requirement: requirement({ id: 2, title: "Modo oscuro", project: "web" }),
      events: [event({ id: 3, meeting_id: 2, kind: "new_requirement", summary: "Tema oscuro", quote: "modo oscuro" })],
    },
  };

  it("summarizes each requirement with its latest state and counts", async () => {
    mockApi(routes);
    renderApp(<Requirements />);
    const card = (await screen.findByRole("heading", { name: "Método de pago" })).closest(".req") as HTMLElement;
    expect(within(card).getByText("Se añade Bizum")).toBeInTheDocument(); // último estado
    expect(within(card).getByText("ha cambiado")).toBeInTheDocument();
    expect(within(card).getByText("2")).toBeInTheDocument();
    expect(within(card).getByText(/2 reuniones/)).toBeInTheDocument();
    const other = screen.getByRole("heading", { name: "Modo oscuro" }).closest(".req") as HTMLElement;
    expect(within(other).queryByText("ha cambiado")).not.toBeInTheDocument();
  });

  it("expands a timeline across meetings with links to the quote", async () => {
    mockApi(routes);
    renderApp(<Requirements />);
    const head = (await screen.findByRole("heading", { name: "Método de pago" })).closest("button")!;
    expect(head).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(head);
    expect(head).toHaveAttribute("aria-expanded", "true");
    const items = document.querySelectorAll(".timeline-item");
    expect(items).toHaveLength(2);
    expect(within(items[0] as HTMLElement).getByRole("link", { name: "Kickoff" })).toHaveAttribute(
      "href",
      "/meetings/1?seg=5",
    );
    expect(within(items[1] as HTMLElement).getByText("Cambio")).toBeInTheDocument();
    expect(within(items[1] as HTMLElement).getByText("también Bizum")).toBeInTheDocument();
  });

  it("filters by project and opens the focused requirement", async () => {
    mockApi(routes);
    renderApp(<Requirements />, { route: "/requirements?focus=2", path: "/requirements" });
    expect((await screen.findByRole("heading", { name: "Modo oscuro" })).closest("button")).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    await userEvent.click(screen.getByRole("button", { name: "#pagos" }));
    expect(screen.queryByRole("heading", { name: "Modo oscuro" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Método de pago" })).toBeInTheDocument();
  });

  it("empty state", async () => {
    mockApi({ "GET /meetings": [], "GET /requirements": [] });
    renderApp(<Requirements />);
    expect(await screen.findByText("Todavía no hay requisitos")).toBeInTheDocument();
  });
});
