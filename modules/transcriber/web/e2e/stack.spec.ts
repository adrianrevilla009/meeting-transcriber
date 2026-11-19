import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

/**
 * E2E de navegador contra el stack de CI (e2e/docker-compose.e2e.yml): transcriptor falso (el "audio" es texto)
 * y un LLM falso (stub) que responde con "ECO-STUB: …". Valida la web real, nginx, la API, el worker, el asistente
 * y privacy-shield trabajando juntos. No se ejecuta contra el stack real (Whisper + Ollama): ese es app.spec.ts.
 */
test.skip(!process.env.MT_E2E_STUB, "Solo contra el stack E2E (transcriptor falso y LLM stub)");

const TOKEN = process.env.MT_API_TOKEN ?? "e2e-mt-token-0123456789abcdef";
const PROJECT = "__e2e_ui__";
const auth = { Authorization: `Bearer ${TOKEN}` };
const QUESTION = "¿Puedes enviar el contrato a Marta García (marta@empresa.es) esta semana?";

async function loggedIn(page: Page) {
  await page.addInitScript((t) => localStorage.setItem("mt_token", t), TOKEN);
}

async function createMeeting(request: APIRequestContext, title: string): Promise<number> {
  const res = await request.post("/api/meetings", { headers: auth, data: { title, project: PROJECT } });
  expect(res.status()).toBe(201);
  return ((await res.json()) as { id: number }).id;
}

async function upload(request: APIRequestContext, id: number, seq: number, text: string, source = "system") {
  const res = await request.post(`/api/meetings/${id}/chunks`, {
    headers: auth,
    multipart: {
      file: { name: "chunk.txt", mimeType: "text/plain", buffer: Buffer.from(text, "utf8") },
      seq: String(seq),
      offset_seconds: String(seq * 20),
      source,
    },
  });
  expect(res.status()).toBe(202);
}

test.afterAll(async ({ request }) => {
  const res = await request.get(`/api/meetings?project=${PROJECT}`, { headers: auth });
  if (!res.ok()) return;
  for (const m of (await res.json()) as { id: number }[]) {
    await request.delete(`/api/meetings/${m.id}`, { headers: auth });
    await request.delete(`/assistant/v1/meetings/${m.id}/follow`, { headers: auth });
  }
});

test("recording in the browser goes through the whole stack and produces a summary", async ({ page }) => {
  test.setTimeout(4 * 60_000);
  const title = `e2e navegador ${Date.now()}`;
  await loggedIn(page);
  await page.goto("/");

  await page.getByRole("button", { name: /Nueva grabación/ }).click();
  await page.getByPlaceholder("Kickoff con cliente").fill(title);
  await page.getByPlaceholder("pagos").fill(PROJECT);
  await page.getByRole("button", { name: /Audio del ordenador/ }).click(); // solo micro en headless
  await page.getByRole("button", { name: "Empezar a grabar" }).click();
  await expect(page.getByText("En directo")).toBeVisible();
  await page.waitForTimeout(16_000); // el micrófono falso reproduce ~15 s de voz
  await page.getByRole("button", { name: "Terminar reunión" }).click();

  await expect(page).toHaveURL(/\/meetings\/\d+$/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.locator(".pill-ready")).toBeVisible({ timeout: 90_000 });
  await expect(page.locator(".summary")).toContainText("RESUMEN-STUB"); // lo generó el LLM de pruebas

  await page.getByRole("button", { name: /Transcripción/ }).click();
  await expect(page.locator(".from-mic").first()).toBeVisible(); // la voz grabada aparece como "Yo"
});

test("the assistant tab answers a manual question through nginx and the privacy filter", async ({ page, request }) => {
  const id = await createMeeting(request, `e2e asistente manual ${Date.now()}`);
  await upload(request, id, 0, "Hola a todos.\nHoy hablamos del presupuesto.");

  await loggedIn(page);
  await page.goto(`/meetings/${id}`);
  await page.getByRole("button", { name: /Asistente/ }).click();
  await expect(page.getByText("Asistente en vivo")).toBeVisible();

  await page.getByLabel("Pregunta para el asistente").fill("¿Qué le digo a Luis Pérez (luis@empresa.es)?");
  await page.getByRole("button", { name: /Preguntar/ }).click();

  const answer = page.locator(".assistant-a").first();
  await expect(answer).toContainText("ECO-STUB", { timeout: 30_000 });
  await expect(answer).toContainText("luis@empresa.es"); // los datos se restauran en la respuesta
  await expect(answer).not.toContainText("[EMAIL_1]");
});

test("a question that arrives in the transcript shows up with its answer while the assistant is on", async ({
  page,
  request,
}) => {
  const id = await createMeeting(request, `e2e asistente en vivo ${Date.now()}`);
  await upload(request, id, 0, "Buenos días a todos.");

  await loggedIn(page);
  await page.goto(`/meetings/${id}`);
  await page.getByRole("button", { name: /Asistente/ }).click();
  await page.getByRole("button", { name: "Activar asistente" }).click();
  await expect(page.getByRole("button", { name: "Desactivar asistente" })).toBeVisible();

  await upload(request, id, 1, QUESTION); // alguien le pregunta en la reunión

  const card = page.locator(".assistant-card").first();
  await expect(card).toContainText("¿Puedes enviar el contrato", { timeout: 45_000 });
  await expect(card.locator(".assistant-a")).toContainText("ECO-STUB", { timeout: 30_000 });
  await expect(card.locator(".assistant-a")).toContainText("Marta García");
  await expect(card.locator(".assistant-a")).not.toContainText("[PERSONA_1]");

  await page.getByRole("button", { name: "Desactivar asistente" }).click();
  await expect(page.getByRole("button", { name: "Activar asistente" })).toBeVisible();
});

test("the sidebar shows the system as online with the LLM ready", async ({ page }) => {
  await loggedIn(page);
  await page.goto("/");
  const card = page.locator(".system-card");
  await expect(card).toContainText("en línea");
  await expect(card.locator(".dot-ok")).toHaveCount(2); // API + LLM listos
});
