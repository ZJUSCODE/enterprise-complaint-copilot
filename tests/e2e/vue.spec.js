const { test, expect } = require("@playwright/test");

async function login(page) {
  await page.goto("/login");
  await page.getByRole("button", { name: "进入工作台" }).click();
  await page.waitForURL("/");
}

test("vue workspace exposes the handling and audit surfaces", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await login(page);
  await expect(page.getByText("Analyst Demo")).toBeVisible();
  await page.getByRole("link", { name: "处理" }).click();
  await expect(page.getByRole("heading", { name: "智能处理" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "客诉处理目标" })).toBeVisible();
  await page.getByRole("link", { name: "审计" }).click();
  await expect(page.getByRole("heading", { name: "每一次 Agent 决策都能回放。" })).toBeVisible();
});

test("mobile vue workspace keeps the route controls usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 860 });
  await login(page);
  await page.getByRole("button", { name: "开始处理" }).click();
  await expect(page.getByRole("heading", { name: "智能处理" })).toBeVisible();
  await expect(page.getByRole("button", { name: "自动判断", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "政策问答", exact: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "客诉处理目标" })).toBeVisible();
});
