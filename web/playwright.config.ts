import { defineConfig } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

// E2E de navegador contra el stack real (make start). Chrome usa un micrófono falso que reproduce
// la voz de tests/fixtures/speech_es.wav, así que el flujo es el mismo que con un micro de verdad.
const fakeAudio = path.resolve(here, "../tests/fixtures/speech_es.wav");

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.MT_E2E_WEB ?? "http://127.0.0.1:3000",
    // Chrome instalado por defecto; PW_CHANNEL= (vacío) usa el Chromium de Playwright.
    channel: process.env.PW_CHANNEL ?? "chrome",
    permissions: ["microphone"],
    actionTimeout: 15_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: {
      args: [
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
        `--use-file-for-fake-audio-capture=${fakeAudio}`,
        "--autoplay-policy=no-user-gesture-required",
      ],
    },
  },
});
