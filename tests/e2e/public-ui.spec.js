const { test, expect } = require('@playwright/test');
const { spawn } = require('child_process');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const FRONTEND_PORT = process.env.PUBLIC_UI_PORT || '5183';
const BACKEND_PORT = process.env.PUBLIC_UI_BACKEND_PORT || '8023';
const FRONTEND_URL = `http://127.0.0.1:${FRONTEND_PORT}`;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;

let frontend;
let backend;
test.setTimeout(90000);

async function waitFor(url, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw lastError || new Error(`Timed out waiting for ${url}`);
}

test.beforeAll(async () => {
  backend = spawn(
    path.join(ROOT, '.venv', 'bin', 'python'),
    ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', BACKEND_PORT],
    {
      cwd: ROOT,
      env: {
        ...process.env,
        AUTH_ENFORCED: 'true',
        REDIS_ENABLED: 'false',
        DATA_QUERY_BACKEND: 'sqlite',
        USE_LANGCHAIN_RAG: 'false',
        LLM_API_KEY: '',
        OPENAI_API_KEY: '',
        EMBEDDING_API_KEY: '',
        JWT_SECRET: 'public-ui-secret',
      },
      stdio: 'pipe',
    },
  );
  frontend = spawn('npm', ['run', 'dev', '--', '--host', '127.0.0.1', '--port', FRONTEND_PORT], {
    cwd: path.join(ROOT, 'frontend'),
    env: { ...process.env, VITE_PROXY_TARGET: BACKEND_URL },
    shell: process.platform === 'win32',
    stdio: 'pipe',
  });
  await waitFor(`${BACKEND_URL}/api/health`);
  await waitFor(`${FRONTEND_URL}/public`);
});

test.afterAll(() => {
  if (frontend && !frontend.killed) frontend.kill('SIGTERM');
  if (backend && !backend.killed) backend.kill('SIGTERM');
});

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
  await page.goto(`${FRONTEND_URL}/public`);
  await expectProductSurface(page);
  await expect(page.getByText('发现风险', { exact: true })).toBeVisible();
  await expect(page.getByText('核验证据', { exact: true })).toBeVisible();
  await expect(page.getByText('复核留痕', { exact: true })).toBeVisible();
});

test('public workspace stays clean on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${FRONTEND_URL}/public`);
  await expectProductSurface(page);
  await expect(page.getByRole('link', { name: '进入工作台' })).toBeVisible();
});

test('authenticated dashboard presents a standard handling flow', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${FRONTEND_URL}/login`);
  await page.getByRole('button', { name: '登录' }).click();
  await page.waitForURL(`${FRONTEND_URL}/`);
  await expect(page.getByText('标准处置流程', { exact: true })).toBeVisible({ timeout: 30000 });
  await expect(page.getByRole('heading', { name: '按证据链完成处理' })).toBeVisible();
  await expect(page.locator('body')).not.toContainText(/面试|求职|Portfolio|Roadmap/i);
  await expect(page.getByText('今日动作', { exact: true })).toHaveCount(0);
  await expect(page.getByText(/异常工单数 =/)).not.toBeVisible();
  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(hasHorizontalOverflow).toBe(false);
});
