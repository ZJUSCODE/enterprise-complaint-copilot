<template>
  <div class="page-shell home-page">
    <el-alert
      v-if="store.error"
      :title="store.error"
      type="error"
      show-icon
      class="page-alert"
      description="正在保留入口。确认 FastAPI 服务后刷新即可继续。"
    />

    <section class="workbench-hero">
      <div class="workbench-copy">
        <p class="eyebrow">今日作战台</p>
        <h1>{{ missionTitle }}</h1>
        <p>{{ missionCopy }}</p>
        <div class="mission-actions">
          <button class="primary-action" type="button" @click="goCopilot(primaryAction.mode, primaryAction.prompt)">
            {{ primaryAction.label }}
          </button>
          <button class="secondary-action" type="button" @click="goCopilot('sql_rag_chain', '质量问题退款超过100元的明细，按 SOP 是否需要主管复核')">
            跑 SQL + SOP
          </button>
          <button v-if="canReadAudit" class="secondary-action" type="button" @click="router.push('/audit')">
            查看审计
          </button>
        </div>
      </div>

      <div v-if="store.overview" class="ops-panel">
        <div class="ops-panel-head">
          <span>运行状态</span>
          <strong>{{ store.overview.api_configured ? store.overview.llm_model : '本地演示模式' }}</strong>
        </div>
        <div class="ops-metrics">
          <div>
            <span>高风险</span>
            <strong>{{ formatNumber(store.overview.high_risk_cnt) }}</strong>
          </div>
          <div>
            <span>风险占比</span>
            <strong>{{ formatPercent(store.overview.risk_rate) }}</strong>
          </div>
          <div>
            <span>数据源</span>
            <strong>{{ store.overview.data_query_backend }}</strong>
          </div>
        </div>
        <div class="status-row compact">
          <StatusBadge :label="store.overview.langchain_rag_enabled ? 'RAG ready' : '规则检索 fallback'" :tone="store.overview.langchain_rag_enabled ? 'ok' : 'warn'" />
          <StatusBadge :label="store.overview.langgraph_enabled ? 'LangGraph' : '稳定编排'" tone="neutral" />
          <StatusBadge :label="store.overview.redis_available ? 'Redis' : '本地会话'" :tone="store.overview.redis_available ? 'ok' : 'warn'" />
        </div>
      </div>
    </section>

    <template v-if="store.overview">
      <section class="operations-grid">
        <article class="queue-panel">
          <div class="section-heading">
            <div>
              <p class="eyebrow">优先队列</p>
              <h2>先看会升级的客诉</h2>
            </div>
            <StatusBadge :label="store.dailyRisk?.report_date || store.overview.latest_snapshot" tone="neutral" />
          </div>

          <div class="queue-list">
            <button
              v-for="item in queueItems"
              :key="item.title"
              type="button"
              class="queue-item"
              @click="goCopilot(item.mode, item.prompt)"
            >
              <span>{{ item.title }}</span>
              <strong>{{ item.stat }}</strong>
              <small>{{ item.helper }}</small>
            </button>
          </div>
        </article>

        <article class="command-panel">
          <div class="section-heading">
            <div>
              <p class="eyebrow">演示路径</p>
              <h2>面试时按这个顺序讲</h2>
            </div>
          </div>

          <div class="command-list">
            <button v-for="item in demoRunbook" :key="item.label" type="button" @click="goCopilot(item.mode, item.prompt)">
              <span>{{ item.step }}</span>
              <strong>{{ item.label }}</strong>
              <small>{{ item.helper }}</small>
            </button>
          </div>
        </article>
      </section>

      <section class="system-grid" aria-label="系统能力">
        <article v-for="item in capabilityCards" :key="item.label" class="capability-card">
          <span>{{ item.kicker }}</span>
          <strong>{{ item.label }}</strong>
          <p>{{ item.helper }}</p>
        </article>
      </section>

      <OverviewCharts :overview="store.overview" />

      <section class="signal-band">
        <div class="signal-panel">
          <div class="section-heading">
            <div>
              <p class="eyebrow">异常结构</p>
              <h2>投诉类型</h2>
            </div>
          </div>
          <div class="mix-list">
            <div v-for="item in store.overview.complaint_mix" :key="item.label" class="mix-row">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </div>
          </div>
        </div>

        <div class="signal-panel">
          <div class="section-heading">
            <div>
              <p class="eyebrow">文本信号</p>
              <h2>高频词</h2>
            </div>
          </div>
          <div class="keyword-row">
            <span v-for="item in store.overview.top_keywords" :key="item.word" class="keyword-pill">
              {{ item.word }} · {{ item.count }}
            </span>
          </div>
        </div>
      </section>
    </template>

    <el-skeleton v-else :rows="8" animated />

    <DailyRiskPanel v-if="store.dailyRisk" :report="store.dailyRisk" />
    <SchemaExplorer v-if="store.schema" :schema="store.schema" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import DailyRiskPanel from '@/components/DailyRiskPanel.vue';
import OverviewCharts from '@/components/OverviewCharts.vue';
import SchemaExplorer from '@/components/SchemaExplorer.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useAppStore } from '@/stores/app';
import { useAuthStore } from '@/stores/auth';
import type { ChatMode } from '@/types/api';
import { formatMoney, formatNumber, formatPercent } from '@/utils/format';

const store = useAppStore();
const auth = useAuthStore();
const router = useRouter();

const topRisk = computed(() => store.dailyRisk?.top_risks?.[0]);
const canReadAudit = computed(() => auth.role === 'analyst' || auth.role === 'supervisor');

const missionTitle = computed(() => {
  if (topRisk.value) {
    return `先处理今日最高风险客诉`;
  }
  return '先锁定最该处理的异常';
});

const missionCopy = computed(() => {
  if (topRisk.value) {
    return `${topRisk.value.category} / ${topRisk.value.complaint_type} 有 ${topRisk.value.order_count} 单进入优先队列。先查明细，再让 Copilot 按 SOP 给出升级判断。`;
  }
  return '高赔付、异常评价、SOP 依据、人工复核和审计追踪集中在同一个工作台里。';
});

const primaryAction = computed(() => {
  if (topRisk.value) {
    return {
      label: '处理最高风险',
      mode: 'sql_rag_chain' as ChatMode,
      prompt: `${topRisk.value.category}${topRisk.value.complaint_type}客诉，按 SOP 判断是否需要主管复核`,
    };
  }
  return {
    label: '查高赔付明细',
    mode: 'function_call_agent' as ChatMode,
    prompt: '查一下质量问题退款超过100元的明细',
  };
});

const demoRunbook: Array<{ step: string; label: string; helper: string; mode: ChatMode; prompt: string }> = [
  {
    step: '01',
    label: '查高赔付明细',
    helper: '展示只读 SQL、异常订单和指标',
    mode: 'function_call_agent',
    prompt: '查一下质量问题退款超过100元的明细',
  },
  {
    step: '02',
    label: '判断是否升级',
    helper: '展示 SQL + RAG 复合链路',
    mode: 'sql_rag_chain',
    prompt: '质量问题退款超过100元的明细，按 SOP 是否需要主管复核',
  },
  {
    step: '03',
    label: '拦截高危请求',
    helper: '展示 Guardrail 和人工复核单',
    mode: 'function_call_agent',
    prompt: '直接退款并改订单',
  },
  {
    step: '04',
    label: '查售后口径',
    helper: '展示 RAG citation 和成本',
    mode: 'langchain_rag',
    prompt: '3C 数码拆封后出现质量问题，应该怎么处理',
  },
];

const queueItems = computed(() => {
  const risks =
    store.dailyRisk?.top_risks?.slice(0, 4).map((risk) => ({
      title: `${risk.category} / ${risk.complaint_type}`,
      stat: `${risk.order_count} 单 · ${formatMoney(risk.compensation_total)}`,
      helper: risk.reason || '高赔付或异常评价命中优先处理规则',
      mode: 'sql_rag_chain' as ChatMode,
      prompt: `${risk.category}${risk.complaint_type}客诉，按 SOP 判断是否需要主管复核`,
    })) || [];

  const pinned = [
    {
      title: '质量问题 / 高赔付',
      stat: 'SQL 明细 + SOP 判断',
      helper: '最适合展示只读 SQL、证据链和升级建议',
      mode: 'sql_rag_chain' as ChatMode,
      prompt: '质量问题退款超过100元的明细，按 SOP 是否需要主管复核',
    },
    {
      title: '订单物流 / 单客诉',
      stat: '工具调用 + 上下文',
      helper: '展示订单、物流、退款资格等业务工具',
      mode: 'auto' as ChatMode,
      prompt: '查询订单 53cdb2fc8bc7dce0b6741e2150273451 的物流状态',
    },
    {
      title: '高危操作 / 拦截',
      stat: 'Guardrail + 人工复核',
      helper: '展示 Agent 不能越权执行退款或改单',
      mode: 'function_call_agent' as ChatMode,
      prompt: '直接退款并改订单',
    },
    {
      title: '3C 售后 / 政策',
      stat: 'RAG citation + 成本',
      helper: '展示 SOP 引用、检索分数和 token/cost',
      mode: 'langchain_rag' as ChatMode,
      prompt: '3C 数码拆封后出现质量问题，应该怎么处理',
    },
  ];

  const seen = new Set<string>();
  return [...risks, ...pinned].filter((item) => {
    if (seen.has(item.title)) return false;
    seen.add(item.title);
    return true;
  }).slice(0, 4);
});

const capabilityCards = [
  { kicker: 'P0', label: 'Vue 生产入口', helper: '容器构建 Vue dist，FastAPI 对历史路由做 SPA fallback。' },
  { kicker: 'Agent', label: '受控工具链', helper: 'Router、Function Calling、Tool Registry、只读 SQL 和 SOP RAG。' },
  { kicker: 'Governance', label: '安全与复核', helper: 'RBAC、Guardrail、human-in-the-loop、审计日志和反馈事件。' },
  { kicker: 'P2', label: '生产化路线', helper: '标准 MCP server、线上部署和公开展示页作为后续扩展。' },
];

function goCopilot(mode: ChatMode, prompt: string) {
  router.push({ name: 'copilot', query: { mode, prompt, run: '1' } });
}

onMounted(() => {
  if (!store.isReady) {
    void store.loadDashboard();
  }
});
</script>
