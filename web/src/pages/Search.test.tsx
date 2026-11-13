import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Search } from "./Search";
import { meeting, mockApi, renderApp } from "../test/utils";

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
