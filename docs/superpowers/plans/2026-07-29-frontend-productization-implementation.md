# Frontend Productization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the portfolio-like frontend into a clean enterprise complaint operations workspace while preserving the existing one-click Agent demonstration flows.

**Architecture:** Keep Vue routes, Pinia stores, API contracts, and prompt behavior unchanged. Refactor only public/home presentation and shared CSS, with a frontend-only Playwright test that verifies product language, navigation, responsive layout, and removal of interview wording.

**Tech Stack:** Vue 3, TypeScript, Element Plus, Vite, Playwright

---

## File Structure

- `frontend/src/views/PublicShowcaseView.vue`: product overview and three-step complaint workflow.
- `frontend/src/views/HomeView.vue`: compact operations dashboard and standard handling playbook.
- `frontend/src/views/LoginView.vue`: remove demo-facing wording from the login surface.
- `frontend/src/assets/styles.css`: shared density, hierarchy, public page, dashboard, and mobile styles.
- `tests/e2e/public-ui.spec.js`: frontend-only product-language and responsive-layout regression tests.

### Task 1: Lock Product Language With A Failing Browser Test

**Files:**
- Create: `tests/e2e/public-ui.spec.js`

- [ ] **Step 1: Add a frontend-only Playwright test**

Create a test that starts Vite on port `5183`, opens `/public`, and asserts:

```js
await expect(page.getByRole("heading", { name: "让高风险客诉更早被看见" })).toBeVisible();
await expect(page.getByText("从风险识别到人工复核，每一步都有依据。" )).toBeVisible();
await expect(page.getByText(/面试|求职|Portfolio|Roadmap|P0|P1|P2/i)).toHaveCount(0);
```

Repeat the absence assertion at a `390 x 844` viewport and verify `document.documentElement.scrollWidth <= window.innerWidth`.

- [ ] **Step 2: Run the new test and verify it fails**

Run: `npx playwright test tests/e2e/public-ui.spec.js --browser=chromium --workers=1`

Expected: FAIL because the current public heading is `企业级智能客诉预警与数据洞察 Copilot` and the page still contains `AI Agent Portfolio` and `Roadmap`.

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/e2e/public-ui.spec.js
git commit -m "test: define productized frontend language"
```

### Task 2: Simplify Public And Login Surfaces

**Files:**
- Modify: `frontend/src/views/PublicShowcaseView.vue`
- Modify: `frontend/src/views/LoginView.vue`
- Modify: `frontend/src/assets/styles.css`
- Test: `tests/e2e/public-ui.spec.js`

- [ ] **Step 1: Replace portfolio content with a product overview**

Use the hero title `让高风险客诉更早被看见`, supporting text about risk identification, evidence verification, SOP guidance, and human review, plus `进入工作台` and `查看处理流程` actions. Replace four engineering cards and the roadmap with three numbered workflow steps: `发现风险`, `核验证据`, `复核留痕`.

- [ ] **Step 2: Remove demo wording from login**

Change `演示账号已准备好` to role-based operational guidance and `查看公开项目页` to `了解平台能力`. Keep credentials and role behavior unchanged.

- [ ] **Step 3: Implement restrained public-page CSS**

Use one unframed hero band, a compact three-column capability strip, a maximum content width of `1080px`, `8px` radii, and existing neutral/green tokens. Remove `.roadmap-list` styling and avoid shadows on content sections.

- [ ] **Step 4: Run the public UI test**

Run: `npx playwright test tests/e2e/public-ui.spec.js --browser=chromium --workers=1`

Expected: PASS on desktop and mobile.

- [ ] **Step 5: Commit the public and login changes**

```bash
git add frontend/src/views/PublicShowcaseView.vue frontend/src/views/LoginView.vue frontend/src/assets/styles.css
git commit -m "feat: productize public complaint workspace"
```

### Task 3: Reduce Dashboard Density And Verify The Full Frontend

**Files:**
- Modify: `frontend/src/views/HomeView.vue`
- Modify: `frontend/src/assets/styles.css`
- Modify: `tests/e2e/public-ui.spec.js`

- [ ] **Step 1: Replace interview runbook language**

Rename `demoRunbook` to `handlingPlaybook`. Render it under `标准处置流程` with the heading `按证据链完成处理`, while keeping the four current modes and prompts unchanged.

- [ ] **Step 2: Flatten the dashboard hierarchy**

Reduce hero height and heading size, merge runtime status into a compact summary, keep the priority queue and handling playbook as the main two-column area, and replace development-stage capability cards with `风险聚合`, `证据驱动`, `受控执行`, and `闭环治理`.

- [ ] **Step 3: Add home-page language assertions**

After logging in as analyst, assert `标准处置流程` and `按证据链完成处理` are visible and `/面试|求职|Portfolio|Roadmap/` is absent from `body` text.

- [ ] **Step 4: Run focused and build checks**

Run:

```bash
npx playwright test tests/e2e/public-ui.spec.js --browser=chromium --workers=1
cd frontend && npm run build
python3 scripts/demo_check.py
```

Expected: Playwright passes, Vue TypeScript/Vite build passes, and `Ready for demo.` is printed.

- [ ] **Step 5: Capture and inspect responsive screenshots**

Capture `/public`, `/login`, and authenticated `/` at `1440 x 1000` and `390 x 844`. Verify no overflow, overlap, clipped actions, or equal-weight section clutter.

- [ ] **Step 6: Commit the dashboard redesign**

```bash
git add frontend/src/views/HomeView.vue frontend/src/assets/styles.css tests/e2e/public-ui.spec.js
git commit -m "feat: simplify complaint operations dashboard"
```

