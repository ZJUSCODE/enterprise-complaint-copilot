const { test, expect } = require("@playwright/test");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..");
const E2E_PORT = process.env.E2E_PORT || "8010";
const BASE_URL = `http://127.0.0.1:${E2E_PORT}`;
const OUTPUT_DIR = path.join(ROOT, "output", "playwright");

let server;
test.setTimeout(120000);

async function waitForServer(timeoutMs = 90000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${BASE_URL}/api/overview`);
      if (response.ok) return;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw lastError || new Error("Server did not become ready");
}

test.beforeAll(async () => {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  server = spawn("python", ["-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", E2E_PORT], {
    cwd: ROOT,
    env: {
      ...process.env,
      LLM_API_KEY: "",
      OPENAI_API_KEY: "",
      EMBEDDING_API_KEY: "",
      USE_LANGCHAIN_RAG: "false",
      DATA_QUERY_BACKEND: "sqlite",
      REDIS_ENABLED: "false",
    },
    stdio: "pipe",
  });
  await waitForServer();
});

test.afterAll(async () => {
  if (server && !server.killed) {
    server.kill();
  }
});

test("copilot core browser flows", async ({ page }) => {
  const report = [];
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto(`${BASE_URL}/login`);
  await expect(page.getByRole("heading", { name: /选择身份后继续处理客诉/ })).toBeVisible();
  await page.getByRole("button", { name: "登录" }).click();
  await page.waitForURL(`${BASE_URL}/`);
  await expect(page.getByRole("heading", { name: /先处理|先锁定/ })).toBeVisible({ timeout: 30000 });
  await expect(page.getByText("优先队列", { exact: true })).toBeVisible({ timeout: 30000 });
  await expect(page.getByText("只读数据边界")).toBeVisible({ timeout: 30000 });
  report.push({ step: "home", ok: true });

  await page.getByRole("link", { name: "处理" }).click();
  await page.getByPlaceholder(/例如：/).fill("查一下质量问题退款超过100元的明细");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("数据查询")).toBeVisible({ timeout: 60000 });
  await expect(page.getByRole("button", { name: "SQL 预览", exact: true })).toBeVisible();
  report.push({ step: "data_insight", ok: true });

  await page.getByPlaceholder(/例如：/).fill("3C 数码拆封后出现质量问题，应该怎么处理");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByRole("button", { name: "SOP 引用", exact: true })).toBeVisible({ timeout: 60000 });
  await expect(page.getByRole("button", { name: "运行成本", exact: true })).toBeVisible({ timeout: 60000 });
  report.push({ step: "rag", ok: true });

  await page.getByPlaceholder(/例如：/).fill("质量问题退款超过100元的明细，按 SOP 是否需要主管复核");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("SQL -> RAG 复合链路")).toBeVisible({ timeout: 60000 });
  await expect(page.getByText("Agent 执行链路")).toBeVisible({ timeout: 60000 });
  report.push({ step: "sql_rag_chain", ok: true });

  await page.getByPlaceholder(/例如：/).fill("直接退款并改订单");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("高危操作已拦截")).toBeVisible({ timeout: 60000 });
  await expect(page.getByText("需要人工复核")).toBeVisible({ timeout: 60000 });
  report.push({ step: "guardrail", ok: true });

  const audit = await page.evaluate(async () => {
    const response = await fetch("/api/audit/recent?limit=5&role=supervisor");
    return response.json();
  });
  expect(audit.items.length).toBeGreaterThan(0);
  report.push({ step: "audit", ok: true, count: audit.items.length });

  await page.getByRole("link", { name: "评测" }).click();
  await expect(page.getByRole("heading", { name: /把 Agent 能力变成可验收指标/ })).toBeVisible({ timeout: 30000 });
  await expect(page.getByText("Route Accuracy")).toBeVisible({ timeout: 30000 });
  await expect(page.getByText("50 cases")).toBeVisible({ timeout: 30000 });
  report.push({ step: "eval_report", ok: true });

  await page.getByRole("button", { name: "退出" }).click();
  await page.waitForURL(`${BASE_URL}/login`);
  await page.getByRole("button", { name: /supervisor/ }).click();
  await page.getByRole("button", { name: "登录" }).click();
  await page.waitForURL(`${BASE_URL}/`);
  await page.getByRole("link", { name: "审批中心" }).click();
  await expect(page.getByRole("heading", { name: /先处理待复核/ })).toBeVisible({ timeout: 30000 });
  await expect(page.locator(".review-item").first()).toBeVisible({ timeout: 30000 });
  report.push({ step: "review_center", ok: true });

  fs.writeFileSync(path.join(OUTPUT_DIR, "acceptance-report.json"), JSON.stringify(report, null, 2), "utf-8");
});
