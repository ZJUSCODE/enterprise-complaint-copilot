<template>
  <div class="page-shell public-page">
    <section class="public-hero">
      <div>
        <p class="eyebrow">AI Agent Portfolio</p>
        <h1>企业级智能客诉预警与数据洞察 Copilot</h1>
        <p>一个把自然语言查询、受控工具调用、只读 SQL、SOP RAG、Guardrail、人工复核和审计追踪串起来的 AI 应用项目。</p>
        <div class="mission-actions">
          <RouterLink class="primary-action" to="/login">进入演示工作台</RouterLink>
          <RouterLink class="secondary-action" to="/copilot">查看处理台</RouterLink>
        </div>
      </div>
    </section>

    <section class="system-grid">
      <article v-for="item in highlights" :key="item.label" class="capability-card">
        <span>{{ item.kicker }}</span>
        <strong>{{ item.label }}</strong>
        <p>{{ item.helper }}</p>
      </article>
    </section>

    <section class="public-roadmap">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Roadmap</p>
          <h2>下一步生产化</h2>
        </div>
      </div>
      <div class="roadmap-list">
        <div v-for="item in roadmap" :key="item.label">
          <span>{{ item.status }}</span>
          <strong>{{ item.label }}</strong>
          <p>{{ item.helper }}</p>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { RouterLink } from 'vue-router';

const highlights = [
  { kicker: 'Agent', label: 'Router + Tool Calling', helper: '按问题自动选择数据工具、SOP 检索或 SQL + RAG 复合链路。' },
  { kicker: 'Safety', label: 'Guardrail + RBAC', helper: '拦截退款、改单、导出用户和 prompt injection，并进入人工复核。' },
  { kicker: 'Evidence', label: 'SQL / Citation / Trace', helper: '前端展示 SQL 预览、RAG 引用、工具轨迹、token 和成本。' },
  { kicker: 'Engineering', label: 'CI + E2E + Docker', helper: 'pytest、Playwright、Vue build、生产镜像和 demo GIF 覆盖核心路径。' },
];

const roadmap = [
  { status: 'P0 done', label: 'Vue 生产入口', helper: '容器构建 Vue dist，FastAPI 提供 SPA fallback。' },
  { status: 'P1 done', label: '审计与 Agent 链路', helper: '审计中心和执行链路可视化已经接入工作台。' },
  { status: 'P2 done', label: 'MCP stdio server', helper: 'Tool Registry 已通过 HTTP JSON-RPC 和 stdio MCP 暴露只读工具。' },
  { status: 'P2 ready', label: '线上部署与公开演示', helper: 'Docker 支持云平台 PORT，Render 蓝图保留 SQLite/fallback 演示路径。' },
];
</script>
