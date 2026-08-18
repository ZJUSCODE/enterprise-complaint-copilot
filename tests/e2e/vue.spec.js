const { test, expect } = require("@playwright/test");
const { spawn } = require("child_process");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..");
const BACKEND_PORT = process.env.VUE_E2E_BACKEND_PORT || "8022";
const FRONTEND_PORT = process.env.VUE_E2E_FRONTEND_PORT || "5182";
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const FRONTEND_URL = `http://127.0.0.1:${FRONTEND_PORT}`;

let backend;
let frontend;
test.setTimeout(150000);

async function waitFor(url, timeoutMs = 90000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status < 500) return;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw lastError || new Error(`Timed out waiting for ${url}`);
}

function spawnLogged(command, args, options) {
  return spawn(command, args, {
    ...options,
    shell: process.platform === "win32",
    stdio: "pipe",
  });
}

function killChild(child) {
  if (!child || child.killed) return;
  if (process.platform === "win32") {
    spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"]);
  } else {
    child.kill("SIGTERM");
  }
}

test.beforeAll(async () => {
  backend = spawnLogged("python", ["-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", BACKEND_PORT], {
    cwd: ROOT,
    env: {
      ...process.env,
      AUTH_ENFORCED: "true",
      REDIS_ENABLED: "false",
      DATA_QUERY_BACKEND: "sqlite",
      USE_LANGCHAIN_RAG: "false",
      LLM_API_KEY: "",
      OPENAI_API_KEY: "",
      EMBEDDING_API_KEY: "",
      JWT_SECRET: "vue-e2e-secret",
    },
  });
  frontend = spawnLogged("npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", FRONTEND_PORT], {
    cwd: path.join(ROOT, "frontend"),
    env: {
      ...process.env,
      VITE_API_BASE_URL: "",
      VITE_PROXY_TARGET: BACKEND_URL,
    },
  });
  await waitFor(`${BACKEND_URL}/api/health`);
  await waitFor(FRONTEND_URL);
});

test.afterAll(async () => {
  killChild(frontend);
  killChild(backend);
});

test("vue workspace login, copilot, guardrail, and review flow", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${FRONTEND_URL}/login`);
  await expect(page.getByRole("heading", { name: /选择身份后继续处理客诉/ })).toBeVisible();
  await page.getByRole("button", { name: "登录" }).click();
  await page.waitForURL(`${FRONTEND_URL}/`);
  await expect(page.getByText("Analyst Demo")).toBeVisible();
  await expect(page.getByRole("heading", { name: /先处理|先锁定/ })).toBeVisible({ timeout: 30000 });

  await page.getByRole("link", { name: "处理" }).click();
  await expect(page.getByRole("heading", { name: /说出目标/ })).toBeVisible();
  await page.getByPlaceholder(/例如：/).fill("质量问题退款超过100元的明细，按 SOP 是否需要主管复核");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("SQL -> RAG 复合链路")).toBeVisible({ timeout: 60000 });
  await expect(page.getByRole("button", { name: "SQL 预览", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "运行成本", exact: true })).toBeVisible();

  await page.getByPlaceholder(/例如：/).fill("直接退款并改订单");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("高危操作已拦截")).toBeVisible({ timeout: 60000 });
  await expect(page.getByText("需要人工复核")).toBeVisible();

  await page.getByRole("link", { name: "审计" }).click();
  await expect(page.getByRole("heading", { name: /每一次 Agent 决策都能回放/ })).toBeVisible();
  await expect(page.locator(".audit-item").first()).toBeVisible({ timeout: 60000 });

  await page.getByRole("button", { name: "退出" }).click();
  await page.waitForURL(`${FRONTEND_URL}/login`);
  await page.getByRole("button", { name: /supervisor/ }).click();
  await page.getByRole("button", { name: "登录" }).click();
  await page.waitForURL(`${FRONTEND_URL}/`);
  await expect(page.getByText("Supervisor Demo")).toBeVisible();

  await page.getByRole("link", { name: "审批中心" }).click();
  await expect(page.getByRole("heading", { name: /先处理待复核/ })).toBeVisible();
  await page.getByRole("button", { name: "生成演示复核单" }).click();
  await expect(page.locator(".review-item").first()).toBeVisible({ timeout: 60000 });
  await expect(page.locator(".review-item").first()).toContainText("优先级");
});

test("mobile vue workspace keeps the agent flow and evidence usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 860 });
  await page.goto(`${FRONTEND_URL}/login`);
  await page.getByRole("button", { name: "登录" }).click();
  await page.waitForURL(`${FRONTEND_URL}/`);
  await expect(page.getByRole("heading", { name: /先处理|先锁定/ })).toBeVisible({ timeout: 30000 });

  await page.getByRole("link", { name: "处理" }).click();
  await expect(page.getByRole("heading", { name: /说出目标/ })).toBeVisible();
  await page.getByPlaceholder(/例如：/).fill("质量问题退款超过100元的明细，按 SOP 是否需要主管复核");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("Agent 执行链路")).toBeVisible({ timeout: 60000 });
  await expect(page.getByRole("button", { name: "SQL 预览", exact: true })).toBeVisible();
});
