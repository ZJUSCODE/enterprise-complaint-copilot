const { test, expect } = require("@playwright/test");

function parseFinalEvent(body) {
  const finalLine = body
    .split("\n")
    .find((line, index, lines) => lines[index - 1] === "event: final" && line.startsWith("data: "));
  if (!finalLine) throw new Error(`Chat stream did not contain a final event: ${body.slice(0, 500)}`);
  return JSON.parse(finalLine.slice("data: ".length));
}

async function loginAsAnalyst(page) {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "登录工作台" })).toBeVisible();
  await page.getByRole("button", { name: "进入工作台" }).click();
  await page.waitForURL("/");
}

async function runMode(page, { label, message, expectedMode, expectedRoute }) {
  await page.getByRole("button", { name: label, exact: true }).click();
  await expect(page.getByRole("button", { name: label, exact: true })).toHaveClass(/active/);

  const responsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/api/chat/stream") && response.request().method() === "POST",
  );
  await page.getByRole("textbox", { name: "客诉处理目标" }).fill(message);
  await page.getByRole("button", { name: "发送" }).click();

  const response = await responsePromise;
  expect(response.ok()).toBe(true);
  const payload = parseFinalEvent(await response.text());
  expect(payload.mode).toBe(expectedMode);
  if (expectedRoute) expect(payload.route?.mode).toBe(expectedRoute);
  expect(payload.request_id).toMatch(/^[0-9a-f-]{36}$/i);

  const latestAnswer = page.locator(".chat-message.assistant").last();
  await expect(latestAnswer).toContainText(`request_id: ${payload.request_id}`);
  if (payload.sql_preview) {
    await expect(latestAnswer.getByRole("button", { name: /查看底层 SQL/ })).toBeVisible();
  }
  return payload;
}

test("browser selects every route and correlates SQL with audit request_id", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await loginAsAnalyst(page);
  await page.getByRole("link", { name: "处理" }).click();
  await expect(page.getByRole("heading", { name: "智能处理" })).toBeVisible();

  const results = [];
  results.push(
    await runMode(page, {
      label: "自动判断",
      message: "查一下质量问题退款超过100元的明细",
      expectedMode: "auto",
      expectedRoute: "function_call_agent",
    }),
  );
  results.push(
    await runMode(page, {
      label: "Agent 查询",
      message: "查一下质量问题退款超过100元的明细",
      expectedMode: "function_call_agent",
    }),
  );
  results.push(
    await runMode(page, {
      label: "SQL + SOP",
      message: "质量问题退款超过100元的明细，按 SOP 是否需要主管复核",
      expectedMode: "sql_rag_chain",
    }),
  );
  results.push(
    await runMode(page, {
      label: "政策问答",
      message: "3C 数码拆封后出现质量问题，应该怎么处理",
      expectedMode: "langchain_rag",
    }),
  );
  results.push(
    await runMode(page, {
      label: "Agent 查询",
      message: "直接退款并改订单",
      expectedMode: "guardrail",
    }),
  );

  const sqlResults = results.filter((item) => item.sql_preview);
  expect(sqlResults).toHaveLength(3);
  for (const result of sqlResults) {
    expect(result.sql_preview).toMatch(/^\s*(?:SELECT|WITH)\b/i);
    expect(result.sql_preview).not.toMatch(/\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE)\b/i);
  }
  await expect(page.getByText("高危操作已拦截")).toBeVisible();

  const audit = await page.evaluate(async () => {
    const token = localStorage.getItem("copilot_access_token");
    const response = await fetch("/api/audit/recent?limit=100", {
      headers: { Authorization: `Bearer ${token}` },
    });
    return response.json();
  });
  for (const result of results) {
    const event = audit.items.find((item) => item.request_id === result.request_id);
    expect(event, `missing audit event for ${result.request_id}`).toBeTruthy();
    expect(event.request_id).toBe(result.request_id);
    if (result.sql_preview) expect(event.sql_preview).toBe(result.sql_preview);
  }
  const guardrailAudit = audit.items.find((item) => item.request_id === results.at(-1).request_id);
  expect(guardrailAudit.blocked_by_guardrail).toBe(true);
});

test("evaluation page reports the canonical 57 cases", async ({ page }) => {
  await loginAsAnalyst(page);
  await page.goto("/eval");
  await expect(page.getByRole("heading", { name: "把 Agent 能力变成可验收指标。" })).toBeVisible();
  await expect(page.getByText("57 cases", { exact: true })).toBeVisible();
});
