const { test, expect } = require('@playwright/test');

async function expectProductSurface(page) {
  await expect(page.getByRole('heading', { name: '让高风险客诉更早被看见' })).toBeVisible();
  await expect(page.getByText('从风险识别到人工复核，每一步都有依据。')).toBeVisible();
  await expect(page.locator('body')).not.toContainText(/面试|求职|Portfolio|Roadmap|P0|P1|P2/i);
  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(hasHorizontalOverflow).toBe(false);
}

test('public workspace uses product language on desktop', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/public');
  await expectProductSurface(page);
  await expect(page.getByText('发现风险', { exact: true })).toBeVisible();
  await expect(page.getByText('核验证据', { exact: true })).toBeVisible();
  await expect(page.getByText('复核留痕', { exact: true })).toBeVisible();
});

test('public workspace stays clean on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/public');
  await expectProductSurface(page);
  await expect(page.getByRole('link', { name: '进入工作台' })).toBeVisible();
});

test('authenticated dashboard presents a standard handling flow', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/login');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await page.waitForURL('/');
  await expect(page.getByRole('heading', { name: '客诉处置概览' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '证据驱动处理' })).toBeVisible();
  await expect(page.locator('body')).not.toContainText(/面试|求职|Portfolio|Roadmap/i);
  await expect(page.getByText('今日动作', { exact: true })).toHaveCount(0);
  await expect(page.getByText(/异常工单数 =/)).not.toBeVisible();
  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(hasHorizontalOverflow).toBe(false);
});
