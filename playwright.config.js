const { defineConfig } = require("@playwright/test");
const fs = require("fs");
const path = require("path");

const ROOT = __dirname;
const PORT = process.env.E2E_PORT || "8010";
const externalBaseUrl = process.env.E2E_BASE_URL;
const baseURL = externalBaseUrl || `http://127.0.0.1:${PORT}`;
const useExternalTerra = process.env.E2E_TERRA_MODE === "external";

if (
  useExternalTerra &&
  !externalBaseUrl &&
  !process.env.LLM_API_KEY &&
  !process.env.OPENAI_API_KEY
) {
  throw new Error("E2E_TERRA_MODE=external requires LLM_API_KEY or OPENAI_API_KEY for a local server.");
}

function resolvePython() {
  const candidates = [
    process.env.E2E_PYTHON,
    path.join(ROOT, ".venv", "bin", "python"),
    "python3",
  ].filter(Boolean);

  return candidates.find((candidate) => candidate === "python3" || fs.existsSync(candidate));
}

const python = resolvePython();
if (!externalBaseUrl && !python) {
  throw new Error("No Python interpreter found. Set E2E_PYTHON or create .venv/bin/python.");
}

const fallbackEnv = useExternalTerra
  ? {}
  : {
      LLM_API_KEY: "",
      OPENAI_API_KEY: "",
      EMBEDDING_API_KEY: "",
      USE_LANGCHAIN_RAG: "false",
    };

module.exports = defineConfig({
  testDir: path.join(ROOT, "tests", "e2e"),
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { outputFolder: "output/playwright/report", open: "never" }]],
  outputDir: "output/playwright/test-results",
  use: {
    baseURL,
    browserName: "chromium",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: externalBaseUrl
    ? undefined
    : {
        command: `"${python}" -m uvicorn main:app --host 127.0.0.1 --port ${PORT}`,
        cwd: ROOT,
        env: {
          ...process.env,
          ...fallbackEnv,
          AUTH_ENFORCED: "true",
          REDIS_ENABLED: "false",
          DATA_QUERY_BACKEND: "sqlite",
          JWT_SECRET: process.env.JWT_SECRET || "playwright-e2e-secret",
        },
        url: `${baseURL}/api/health`,
        timeout: 120_000,
        reuseExistingServer: false,
        stdout: "pipe",
        stderr: "pipe",
      },
});
