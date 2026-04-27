<template>
  <div class="page-shell eval-page">
    <section class="eval-hero">
      <div>
        <p class="eyebrow">评测报告</p>
        <h1>把 Agent 能力变成可验收指标。</h1>
        <p>展示 route、tool selection、RAG citation、Guardrail、memory follow-up、latency 和 retry 的离线评测结果。</p>
      </div>
      <button class="secondary-action" type="button" :disabled="loading" @click="loadReport">
        刷新
      </button>
    </section>

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      class="page-alert"
      description="评测报告需要 analyst 或 supervisor 权限。"
    />

    <section v-if="report" class="eval-summary-grid">
      <article class="metric-card">
        <span>总用例</span>
        <strong>{{ report.total.all_cases }}</strong>
        <p>{{ report.evaluation_mode }} / {{ report.rag_status }}</p>
      </article>
      <article class="metric-card">
        <span>路由准确率</span>
        <strong>{{ percent(report.metrics.route_accuracy) }}</strong>
        <p>自然语言目标能否进入正确链路</p>
      </article>
      <article class="metric-card">
        <span>工具选择</span>
        <strong>{{ percent(report.metrics.tool_selection_accuracy) }}</strong>
        <p>订单、物流、退款、市场政策等工具</p>
      </article>
      <article class="metric-card">
        <span>安全拦截</span>
        <strong>{{ percent(report.metrics.guardrail_interception) }}</strong>
        <p>注入、写 SQL、退款、导出等高危请求</p>
      </article>
    </section>

    <section v-if="report" class="eval-board" v-loading="loading">
      <div class="section-heading">
        <div>
          <p class="eyebrow">指标矩阵</p>
          <h2>核心能力覆盖</h2>
        </div>
        <StatusBadge :label="report.report_path || 'eval/v2_eval_report.json'" tone="neutral" />
      </div>

      <div class="eval-metric-list">
        <article v-for="item in metricItems" :key="item.key" class="eval-metric-row">
          <div>
            <strong>{{ item.label }}</strong>
            <span>{{ item.helper }}</span>
          </div>
          <div class="eval-score">
            <el-progress :percentage="item.percent" :stroke-width="10" :show-text="false" />
            <b>{{ item.value }}</b>
          </div>
        </article>
      </div>
    </section>

    <section v-if="report" class="eval-grid">
      <article class="eval-panel">
        <div class="panel-head">
          <div>
            <p class="eyebrow">Case Counts</p>
            <h2>测试套件</h2>
          </div>
          <StatusBadge :label="`${report.total.all_cases} cases`" tone="ok" />
        </div>
        <div class="eval-suite-list">
          <span>RAG <b>{{ report.total.rag_cases }}</b></span>
          <span>Route <b>{{ report.total.route_cases }}</b></span>
          <span>Tool <b>{{ report.total.tool_cases }}</b></span>
          <span>Guardrail <b>{{ report.total.guardrail_cases }}</b></span>
          <span>Memory <b>{{ report.total.memory_cases }}</b></span>
        </div>
      </article>

      <article class="eval-panel">
        <div class="panel-head">
          <div>
            <p class="eyebrow">Latency</p>
            <h2>运行效率</h2>
          </div>
          <StatusBadge label="offline" tone="neutral" />
        </div>
        <div class="latency-strip">
          <span>P50 <b>{{ report.metrics.latency_p50_ms }} ms</b></span>
          <span>P95 <b>{{ report.metrics.latency_p95_ms }} ms</b></span>
          <span>Retry <b>{{ percent(report.metrics.retry_success_rate) }}</b></span>
        </div>
      </article>
    </section>

    <section v-if="report" class="eval-board">
      <div class="section-heading">
        <div>
          <p class="eyebrow">样例回放</p>
          <h2>最近评测样本</h2>
        </div>
        <StatusBadge :label="`${sampleRows.length} 条`" tone="neutral" />
      </div>

      <div class="eval-case-list">
        <article v-for="item in sampleRows" :key="item.id" class="eval-case-item">
          <div>
            <el-tag size="small" effect="plain">{{ item.suite }}</el-tag>
            <strong>{{ item.question }}</strong>
            <p>{{ item.expectation }}</p>
          </div>
          <StatusBadge :label="item.hit ? 'pass' : 'check'" :tone="item.hit ? 'ok' : 'warn'" />
        </article>
      </div>
    </section>

    <section v-if="!report && !loading && !error" class="empty-state">
      <p>暂无评测报告。先运行 `python scripts\\evaluate_rag.py --force-lexical`。</p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { getEvalReport } from '@/api/client';
import { useAuthStore } from '@/stores/auth';
import type { EvalReport } from '@/types/api';

const auth = useAuthStore();
const loading = ref(false);
const error = ref('');
const report = ref<EvalReport | null>(null);

const metricItems = computed(() => {
  if (!report.value) return [];
  const metrics = report.value.metrics;
  return [
    { key: 'route_accuracy', label: 'Route Accuracy', helper: '数据、政策、SQL + RAG、英文工具意图', raw: metrics.route_accuracy },
    { key: 'tool_selection_accuracy', label: 'Tool Selection', helper: '订单、物流、退款资格、市场政策、用户风险', raw: metrics.tool_selection_accuracy },
    { key: 'citation_hit_rate', label: 'Citation Hit Rate', helper: 'SOP 引用命中与可追溯性', raw: metrics.citation_hit_rate },
    { key: 'negative_abstention_rate', label: 'Abstention', helper: '无答案时不编造规则', raw: metrics.negative_abstention_rate },
    { key: 'guardrail_interception', label: 'Guardrail', helper: 'Prompt injection、写 SQL、高危动作拦截', raw: metrics.guardrail_interception },
    { key: 'memory_followup_accuracy', label: 'Memory Follow-up', helper: '多轮追问复用订单号上下文', raw: metrics.memory_followup_accuracy },
  ].map((item) => ({ ...item, percent: Math.round(item.raw * 100), value: percent(item.raw) }));
});

const sampleRows = computed(() => {
  if (!report.value) return [];
  const rows = report.value.rows;
  return [
    ...rows.rag.slice(0, 3).map((row, index) => ({
      id: `rag-${index}`,
      suite: 'RAG',
      question: row.question,
      expectation: `expected ${row.expected_doc_id || '-'} / returned ${(row.returned_doc_ids || []).join(', ') || '-'}`,
      hit: row.hit !== false,
    })),
    ...rows.route.slice(0, 2).map((row, index) => ({
      id: `route-${index}`,
      suite: 'Route',
      question: row.question,
      expectation: `expected ${row.expected_mode || '-'} / actual ${row.actual_mode || '-'}`,
      hit: row.hit !== false,
    })),
    ...rows.tool.slice(0, 2).map((row, index) => ({
      id: `tool-${index}`,
      suite: 'Tool',
      question: row.question,
      expectation: `expected ${row.expected_tool || '-'} / actual ${row.actual_tool || '-'}`,
      hit: row.hit !== false,
    })),
    ...rows.guardrail.slice(0, 2).map((row, index) => ({
      id: `guardrail-${index}`,
      suite: 'Guardrail',
      question: row.question,
      expectation: `blocked ${row.blocked === true ? 'yes' : 'no'}`,
      hit: row.blocked === row.expected_blocked || row.blocked === true,
    })),
  ];
});

function percent(value: number | undefined) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

async function loadReport() {
  loading.value = true;
  error.value = '';
  try {
    const payload = await getEvalReport(auth.role || 'analyst');
    if (payload.error) {
      error.value = payload.error.message;
      report.value = null;
      return;
    }
    report.value = payload;
  } catch (err) {
    error.value = err instanceof Error ? err.message : '评测报告加载失败';
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void loadReport();
});
</script>
