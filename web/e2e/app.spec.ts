import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

/** Token de MT_API_TOKEN o, si no, del .env del proyecto. */
function token(): string {
  if (process.env.MT_API_TOKEN) return process.env.MT_API_TOKEN;
  const env = path.resolve(here, "../../.env");
  const line = fs.existsSync(env) ? fs.readFileSync(env, "utf8").split(/\r?\n/).find((l) => l.startsWith("MT_API_TOKEN=")) : undefined;
  if (!line) throw new Error("Define MT_API_TOKEN o crea .env");
  return line.slice("MT_API_TOKEN=".length).trim();
}

const PROJECT = "__e2e__";
const auth = { Authorization: `Bearer ${token()}` };

async function loggedIn(page: Page) {
  await page.addInitScript((t) => localStorage.setItem("mt_token", t), token());
}

async function cleanup(request: APIRequestContext) {
  const res = await request.get(`/api/meetings?project=${PROJECT}`, { headers: auth });
  if (!res.ok()) return;
  for (const m of (await res.json()) as { id: number }[]) await request.delete(`/api/meetings/${m.id}`, { headers: auth });
}

test.beforeAll(async ({ request }) => {
  const health = await request.get("/api/health").catch(() => null);
  test.skip(!health?.ok(), "El stack no responde: lanza make start");
});
test.afterAll(async ({ request }) => cleanup(request));

test("login rejects a wrong token and accepts the right one", async ({ page }) => {
  await page.goto("/");
  await page.getByPlaceholder(/MT_API_TOKEN/).fill("token-incorrecto");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByText("Ese token no es válido.")).toBeVisible();

  await page.getByPlaceholder(/MT_API_TOKEN/).fill(token());
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { name: /Graba\. Transcribe\./ })).toBeVisible();

  await page.reload(); // el token persiste
  await expect(page.getByRole("navigation").getByRole("link", { name: "Reuniones" })).toBeVisible();
  await page.getByRole("button", { name: "Salir" }).click();
  await expect(page.getByPlaceholder(/MT_API_TOKEN/)).toBeVisible();
});

test("sidebar shows the system status", async ({ page }) => {
  await loggedIn(page);
  await page.goto("/");
  const card = page.locator(".system-card");
  await expect(card).toContainText("en línea");
  await expect(card).toContainText("Whisper");
  await expect(card.locator(".dot-ok")).toHaveCount(2); // API + LLM listos
});

test("record from the browser → Whisper → LLM → insights, search and delete", async ({ page }) => {
  test.setTimeout(8 * 60_000);
  const title = `e2e navegador ${Date.now()}`;
  await loggedIn(page);
  await page.goto("/");

  // 1. Grabar desde la UI con el micrófono falso (voz del fixture).
  await page.getByRole("button", { name: /Nueva grabación/ }).click();
  await page.getByPlaceholder("Kickoff con cliente").fill(title);
  await page.getByPlaceholder("pagos").fill(PROJECT);
  await page.getByRole("button", { name: /Audio del ordenador/ }).click(); // solo micro en headless
  await page.getByRole("button", { name: "Empezar a grabar" }).click();

  await expect(page.getByText("En directo")).toBeVisible();
  await expect(page.locator(".lane")).toHaveCount(1);
  await expect(page.locator(".live-badge")).toBeVisible(); // indicador en la barra lateral
  await page.waitForTimeout(16_000); // el audio del fixture dura ~15 s
  await page.getByRole("button", { name: "Terminar reunión" }).click();

  // 2. La app lleva a la reunión y muestra el progreso hasta terminar.
  await expect(page).toHaveURL(/\/meetings\/\d+$/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.locator(".pill-ready")).toBeVisible({ timeout: 6 * 60_000 });

  // 3. Análisis con IA: hallazgos con cita.
  await expect(page.locator(".insight").first()).toBeVisible();
  await expect(page.locator(".insight blockquote").first()).not.toBeEmpty();

  // 4. Transcripción: la voz grabada aparece como "Yo".
  await page.getByRole("button", { name: /Transcripción/ }).click();
  await expect(page.locator(".from-mic").first()).toBeVisible();
  await expect(page.locator(".chat")).toContainText(/tarjeta/i);
  await expect(page.locator(".chat")).toContainText(/bizum/i);

  // 5. El salto desde un hallazgo resalta la frase.
  await page.getByRole("button", { name: /Análisis IA/ }).click();
  await page.locator(".ts-link").first().click();
  await expect(page).toHaveURL(/\?seg=\d+/);
  await expect(page.locator(".bubble-row.flash")).toHaveCount(1);
  const meetingUrl = page.url().split("?")[0];

  // 6. Buscar la frase en todas las reuniones lleva de vuelta a ella.
  await page.getByRole("navigation").getByRole("link", { name: "Buscar" }).click();
  await page.getByPlaceholder(/presupuesto/).fill("tarjeta");
  const group = page.locator(".search-group", { hasText: title });
  await expect(group).toBeVisible();
  await group.locator(".search-hit").first().click();
  await expect(page).toHaveURL(new RegExp(`${meetingUrl.split("/").pop()}\\?seg=`));

  // 7. Aparece en el panel con su proyecto.
  await page.getByRole("navigation").getByRole("link", { name: "Reuniones" }).click();
  await page.getByRole("button", { name: `#${PROJECT}` }).click();
  await expect(page.locator(".meeting-card", { hasText: title })).toContainText("Lista");

  // 8. Borrar exige confirmación y elimina la reunión.
  await page.locator(".meeting-card", { hasText: title }).click();
  await page.getByRole("button", { name: /Eliminar/ }).click();
  await page.getByRole("button", { name: /Seguro/ }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByText("Reunión eliminada")).toBeVisible();
  await expect(page.locator(".meeting-card", { hasText: title })).toHaveCount(0);
});

test("requirements page loads and expands a requirement", async ({ page, request }) => {
  await loggedIn(page);
  const reqs = await (await request.get("/api/requirements", { headers: auth })).json();
  await page.goto("/requirements");
  if (!reqs.length) {
    await expect(page.getByText("Todavía no hay requisitos")).toBeVisible();
    return;
  }
  const first = page.locator(".req-head").first();
  await first.click();
  await expect(first).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(".timeline-item").first()).toBeVisible();
});

test("unknown routes fall back to the dashboard", async ({ page }) => {
  await loggedIn(page);
  await page.goto("/no-existe");
  await expect(page).toHaveURL(/\/$/);
});
