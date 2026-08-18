<template>
  <div class="workspace-page home-page">
    <header class="page-header">
      <div>
        <p>{{ sampleLabel }}</p>
        <h1>客诉处置概览</h1>
      </div>
      <button class="primary-action" type="button" @click="goCopilot(primaryAction.mode, primaryAction.prompt)">
        开始处理
        <ArrowRight />
      </button>
    </header>

    <el-alert v-if="store.error" :title="store.error" type="error" show-icon class="page-alert" />

    <template v-if="store.overview">
      <section class="summary-strip" aria-label="样本概览">
        <div>
          <span>高风险用户</span>
          <strong>{{ formatNumber(store.overview.high_risk_cnt) }}</strong>
          <small>风险占比 {{ formatPercent(store.overview.risk_rate) }}</small>
        </div>
        <div>
          <span>待优先处理</span>
          <strong>{{ priorityCount }}</strong>
          <small>按赔付和评价排序</small>
        </div>
        <div>
          <span>模型状态</span>
          <strong class="model-name">Terra</strong>
          <small>{{ store.overview.rag_retrieval_mode === 'vector' ? '向量检索' : '词法检索 + 模型生成' }}</small>
        </div>
        <div>
          <span>数据边界</span>
          <strong class="model-name">只读</strong>
          <small>{{ store.overview.data_query_backend.toUpperCase() }} · SELECT only</small>
        </div>
      </section>

      <section class="operations-grid">
        <article class="queue-panel">
          <div class="section-heading">
            <div>
              <span>优先队列</span>
              <h2>需要先处理的异常</h2>
            </div>
            <small>{{ store.dailyRisk?.report_date || store.overview.latest_snapshot }}</small>
          </div>

          <div class="queue-table" role="table" aria-label="优先客诉队列">
            <div class="queue-table-head" role="row">
              <span>问题</span><span>规模</span><span>建议动作</span><span />
            </div>
            <button
              v-for="item in queueItems"
              :key="item.title"
              type="button"
              class="queue-row"
              role="row"
              @click="goCopilot(item.mode, item.prompt)"
            >
              <span class="queue-main"><strong>{{ item.title }}</strong><small>{{ item.helper }}</small></span>
              <span class="queue-stat"><small>规模</small>{{ item.stat }}</span>
              <span class="queue-action"><small>建议动作</small>{{ item.action }}</span>
              <ArrowRight />
            </button>
          </div>
        </article>

        <aside class="workflow-panel">
          <div class="section-heading">
            <div>
              <span>标准流程</span>
              <h2>证据驱动处理</h2>
            </div>
          </div>
          <ol class="workflow-list">
            <li v-for="item in handlingPlaybook" :key="item.label">
              <button type="button" @click="goCopilot(item.mode, item.prompt)">
                <span>{{ item.step }}</span>
                <span><strong>{{ item.label }}</strong><small>{{ item.helper }}</small></span>
                <ArrowRight />
              </button>
            </li>
          </ol>
        </aside>
      </section>

      <OverviewCharts :overview="store.overview" />

      <section class="signal-band">
        <div class="signal-panel">
          <div class="section-heading"><div><span>异常结构</span><h2>投诉类型</h2></div></div>
          <div class="mix-list">
            <div v-for="item in store.overview.complaint_mix" :key="item.label" class="mix-row">
              <span>{{ item.label }}</span><strong>{{ item.value }}</strong>
            </div>
          </div>
        </div>
        <div class="signal-panel">
          <div class="section-heading"><div><span>文本信号</span><h2>高频问题</h2></div></div>
          <div class="keyword-list">
            <div v-for="item in store.overview.top_keywords" :key="item.word">
              <span>{{ item.word }}</span><strong>{{ item.count }}</strong>
            </div>
          </div>
          <p v-if="!store.overview.top_keywords.length" class="signal-empty">当前数据范围内暂无高频问题</p>
        </div>
      </section>

      <SchemaExplorer v-if="store.schema" :schema="store.schema" />
    </template>

    <el-skeleton v-else :rows="8" animated />
  </div>
</template>

<script setup lang="ts">
import { ArrowRight } from '@element-plus/icons-vue';
import { computed, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import OverviewCharts from '@/components/OverviewCharts.vue';
import SchemaExplorer from '@/components/SchemaExplorer.vue';
import { useAppStore } from '@/stores/app';
import type { ChatMode } from '@/types/api';
import { formatMoney, formatNumber, formatPercent } from '@/utils/format';

const store = useAppStore();
const router = useRouter();
const sampleLabel = computed(() => store.overview
  ? `${store.overview.latest_snapshot.slice(0, 4)} 合成演示数据 · 数据覆盖至 ${store.overview.latest_snapshot}`
  : '正在读取演示数据');
const priorityCount = computed(() => store.dailyRisk?.top_risks?.reduce((sum, item) => sum + item.order_count, 0) || 0);
const topRisk = computed(() => store.dailyRisk?.top_risks?.[0]);
const primaryAction = computed(() => ({
  mode: 'sql_rag_chain' as ChatMode,
  prompt: topRisk.value
    ? `${topRisk.value.category}${topRisk.value.complaint_type}客诉，按 SOP 判断是否需要主管复核`
    : '质量问题退款超过100元的明细，按 SOP 是否需要主管复核',
}));

const handlingPlaybook: Array<{ step: string; label: string; helper: string; mode: ChatMode; prompt: string }> = [
  { step: '01', label: '查询异常明细', helper: 'Terra 解析条件并生成只读查询', mode: 'function_call_agent', prompt: '查一下质量问题退款超过100元的明细' },
  { step: '02', label: '核对 SOP', helper: '结合业务数据生成处理依据', mode: 'sql_rag_chain', prompt: '质量问题退款超过100元的明细，按 SOP 是否需要主管复核' },
  { step: '03', label: '进入人工复核', helper: '高风险或规则缺口转主管判断', mode: 'auto', prompt: '请判断今天最需要优先人工复核的客诉并说明原因' },
];

const queueItems = computed(() => {
  const risks = store.dailyRisk?.top_risks?.slice(0, 4).map((risk) => ({
    title: `${risk.category} · ${risk.complaint_type}`,
    stat: `${risk.order_count} 单 / ${formatMoney(risk.compensation_total)}`,
    helper: risk.reason || '高赔付或异常评价',
    action: 'SQL + SOP 判断',
    mode: 'sql_rag_chain' as ChatMode,
    prompt: `${risk.category}${risk.complaint_type}客诉，按 SOP 判断是否需要主管复核`,
  })) || [];
  return risks.length ? risks : [{
    title: '质量问题 · 高赔付', stat: '查看异常明细', helper: '赔付金额超过 100 元', action: '生成处理建议',
    mode: 'sql_rag_chain' as ChatMode, prompt: '质量问题退款超过100元的明细，按 SOP 是否需要主管复核',
  }];
});

function goCopilot(mode: ChatMode, prompt: string) {
  void router.push({ name: 'copilot', query: { mode, prompt, run: '1' } });
}

onMounted(() => {
  if (!store.isReady) void store.loadDashboard();
});
</script>
