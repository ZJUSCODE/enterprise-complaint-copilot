<template>
  <aside class="evidence-rail">
    <div class="rail-head">
      <p class="eyebrow">证据</p>
      <h2>{{ message ? '本轮依据' : '等待提问' }}</h2>
      <p>{{ message ? '默认只看结论。需要追溯时，再展开细节。' : '提问后会自动整理 SQL、引用和执行轨迹。' }}</p>
    </div>

    <template v-if="message">
      <AgentFlow :message="message" />

      <section v-if="message.review_case" class="review-callout">
        <div>
          <span>需要人工复核</span>
          <strong>{{ reviewStatusLabel(message.review_case.status) }}</strong>
        </div>
        <p>{{ message.review_case.reason }}</p>
        <RouterLink class="text-link" to="/review">去审批中心</RouterLink>
      </section>

      <el-collapse v-if="hasEvidence" v-model="openPanels" class="evidence-collapse">
        <el-collapse-item v-if="message.sql_preview" title="SQL 预览" name="sql">
          <SqlPreview :sql="message.sql_preview" />
          <div class="sql-actions">
            <button
              v-if="message?.table?.length"
              type="button"
              class="text-link"
              @click="exportTableCsv(message.table, message.request_id)"
            >
              导出数据
            </button>
          </div>
        </el-collapse-item>
        <el-collapse-item v-if="message.query_plan?.steps?.length" title="查询计划" name="plan">
          <div class="query-plan-detail">
            <div v-for="step in message.query_plan.steps" :key="step.step_id" class="plan-step">
              <span class="plan-id">{{ step.step_id }}</span>
              <span class="plan-query">{{ step.query }}</span>
              <span class="plan-tool">{{ step.expected_tool }}</span>
            </div>
            <p class="plan-method">分解方式：{{ message.query_plan.decomposition_method }}</p>
          </div>
        </el-collapse-item>
        <el-collapse-item v-if="message.citations?.length" title="SOP 引用" name="citations">
          <RagCitations :items="message.citations" />
          <div v-if="message.citation_highlights?.length" class="citation-mapping">
            <p class="mapping-title">引用-回答映射</p>
            <div v-for="m in message.citation_highlights" :key="m.citation_index" class="mapping-row">
              <span class="mapping-label">{{ m.citation_label }}</span>
              <span class="mapping-arrow">&rarr;</span>
              <span class="mapping-excerpt">{{ m.answer_excerpt }}</span>
              <span class="mapping-score">{{ (m.match_score * 100).toFixed(0) }}%</span>
            </div>
          </div>
        </el-collapse-item>
        <el-collapse-item v-if="message.tool_trace?.length" title="执行轨迹" name="trace">
          <ToolTrace :items="message.tool_trace" />
        </el-collapse-item>
        <el-collapse-item v-if="message.token_usage || message.estimated_cost_usd !== undefined" title="运行成本" name="runtime">
          <div class="runtime-detail">
            <span v-if="message.token_usage">tokens {{ message.token_usage.total_tokens }}</span>
            <span v-if="message.token_usage?.embedding_tokens !== undefined">embedding {{ message.token_usage.embedding_tokens }}</span>
            <span v-if="message.token_usage">prompt {{ message.token_usage.prompt_tokens }}</span>
            <span v-if="message.token_usage">completion {{ message.token_usage.completion_tokens }}</span>
            <strong>cost ${{ Number(message.estimated_cost_usd || 0).toFixed(6) }}</strong>
          </div>
        </el-collapse-item>
        <el-collapse-item v-if="message.online_rag_metrics || message.query_rewrite" title="RAG 质量指标" name="rag_metrics">
          <div class="rag-metrics-detail">
            <div v-if="message.retrieval_mode" class="metric-row">
              <span class="metric-label">检索模式</span>
              <span class="metric-value">{{ message.retrieval_mode }}</span>
            </div>
            <div v-if="message.query_rewrite" class="metric-row">
              <span class="metric-label">查询重写</span>
              <span class="metric-value">{{ message.query_rewrite.method }} ({{ message.query_rewrite.rewrite_ms }}ms)</span>
            </div>
            <div v-if="message.query_rewrite && message.query_rewrite.original !== message.query_rewrite.rewritten" class="rewrite-detail">
              <p><strong>原问题：</strong>{{ message.query_rewrite.original }}</p>
              <p><strong>改写后：</strong>{{ message.query_rewrite.rewritten }}</p>
            </div>
            <div v-if="message.reflection" class="metric-row">
              <span class="metric-label">回答自检</span>
              <span class="metric-value" :style="{ color: message.reflection.passed ? '#67c23a' : '#e6a23c' }">{{ message.reflection.passed ? '通过' : '有问题' }}</span>
            </div>
            <div v-if="message.reflection && !message.reflection.passed" class="rewrite-detail">
              <p v-for="issue in message.reflection.issues" :key="issue">{{ issue }}</p>
            </div>
            <template v-if="message.online_rag_metrics">
              <div class="metric-row">
                <span class="metric-label">检索多样性</span>
                <span class="metric-value">{{ message.online_rag_metrics.retrieval_diversity }}</span>
              </div>
              <div class="metric-row">
                <span class="metric-label">检索置信度</span>
                <span class="metric-value">{{ message.online_rag_metrics.retrieval_confidence }}</span>
              </div>
              <div class="metric-row">
                <span class="metric-label">查询覆盖率</span>
                <span class="metric-value">{{ message.online_rag_metrics.coverage_score }}</span>
              </div>
            </template>
          </div>
        </el-collapse-item>
        <el-collapse-item v-if="message.modular_rag_metrics" title="Modular RAG 模块" name="modular_rag">
          <div class="modular-rag-detail">
            <div class="metric-row">
              <span class="metric-label">检索策略</span>
              <span class="metric-value">{{ message.modular_rag_metrics.retrieval_strategy }}</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">CRAG 状态</span>
              <span class="metric-value" :style="{ color: message.modular_rag_metrics.crag_status === 'passed' ? '#67c23a' : '#e6a23c' }">{{ message.modular_rag_metrics.crag_status }}</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">Self-RAG</span>
              <span class="metric-value" :style="{ color: message.modular_rag_metrics.self_rag_passed ? '#67c23a' : '#e6a23c' }">{{ message.modular_rag_metrics.self_rag_passed ? '通过' : '未通过' }}</span>
            </div>
            <div v-if="message.modular_rag_metrics.kg_entities.length" class="metric-row">
              <span class="metric-label">图谱实体</span>
              <span class="metric-value">{{ message.modular_rag_metrics.kg_entities.join(', ') }}</span>
            </div>
            <div v-if="message.modular_rag_metrics.kg_triples" class="metric-row">
              <span class="metric-label">图谱三元组</span>
              <span class="metric-value">{{ message.modular_rag_metrics.kg_triples }}</span>
            </div>
            <div class="module-tags">
              <p class="mapping-title">激活模块</p>
              <div class="tag-list">
                <span v-for="mod in message.modular_rag_metrics.activated_modules" :key="mod" class="module-tag activated">{{ mod }}</span>
              </div>
              <p v-if="message.modular_rag_metrics.skipped_modules.length" class="mapping-title" style="margin-top: 8px;">跳过模块</p>
              <div class="tag-list">
                <span v-for="mod in message.modular_rag_metrics.skipped_modules" :key="mod" class="module-tag skipped">{{ mod }}</span>
              </div>
            </div>
            <div v-if="Object.keys(message.modular_rag_metrics.module_timings).length" class="timing-bars">
              <p class="mapping-title">模块耗时</p>
              <div v-for="(ms, mod) in message.modular_rag_metrics.module_timings" :key="mod" class="timing-bar-row">
                <span class="timing-label">{{ mod }}</span>
                <div class="timing-bar">
                  <div class="timing-fill" :style="{ width: Math.min(ms / 100, 100) + '%' }"></div>
                </div>
                <span class="timing-value">{{ ms }}ms</span>
              </div>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>

      <section v-else class="empty-state">
        <p>本轮没有返回 SQL、RAG 或工具轨迹。</p>
      </section>
    </template>

    <section v-else class="empty-state">
      <p>先输入一个业务目标。结论会留在对话区，证据会留在这里。</p>
    </section>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';
import AgentFlow from '@/components/AgentFlow.vue';
import RagCitations from '@/components/RagCitations.vue';
import SqlPreview from '@/components/SqlPreview.vue';
import ToolTrace from '@/components/ToolTrace.vue';
import type { ChatResponse } from '@/types/api';
import { reviewStatusLabel } from '@/utils/format';

const props = defineProps<{
  message: ChatResponse | null;
}>();

const openPanels = ref<string[]>([]);

const hasEvidence = computed(() => {
  const message = props.message;
  return Boolean(
    message?.sql_preview ||
      message?.citations?.length ||
      message?.tool_trace?.length ||
      message?.token_usage ||
      message?.estimated_cost_usd !== undefined ||
      message?.online_rag_metrics ||
      message?.query_rewrite ||
      message?.reflection ||
      message?.query_plan?.steps?.length ||
      message?.citation_highlights?.length ||
      message?.modular_rag_metrics,
  );
});

watch(
  () => props.message?.request_id,
  () => {
    const next: string[] = [];
    if (props.message?.review_case) next.push('runtime');
    if (props.message?.sql_preview) next.push('sql');
    openPanels.value = next.slice(0, 1);
  },
  { immediate: true },
);

function exportTableCsv<T extends object>(table: T[], requestId?: string) {
  if (!table.length) return;
  const headers = Object.keys(table[0]) as Array<keyof T>;
  const csvRows = [headers.join(',')];
  for (const row of table) {
    csvRows.push(headers.map((h) => String(row[h] ?? '')).join(','));
  }
  const blob = new Blob(['﻿' + csvRows.join('\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `copilot_export_${(requestId || 'data').slice(0, 8)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

defineExpose({
  openSqlPanel() {
    if (!openPanels.value.includes('sql')) {
      openPanels.value = [...openPanels.value, 'sql'];
    }
  },
});
</script>

<style scoped>
.sql-actions {
  margin-top: 8px;
}
.sql-actions .text-link {
  background: none;
  border: none;
  color: var(--el-color-primary);
  cursor: pointer;
  font-size: 13px;
  padding: 0;
  text-decoration: underline;
}
.rag-metrics-detail {
  font-size: 13px;
}
.metric-row {
  display: flex;
  justify-content: space-between;
  padding: 3px 0;
}
.metric-label {
  color: #666;
}
.metric-value {
  font-weight: 500;
}
.rewrite-detail {
  margin-top: 6px;
  padding: 6px 8px;
  background: #f5f7fa;
  border-radius: 4px;
  font-size: 12px;
}
.rewrite-detail p {
  margin: 2px 0;
}
.citation-mapping {
  margin-top: 8px;
  padding: 6px 8px;
  background: #f5f7fa;
  border-radius: 4px;
  font-size: 12px;
}
.mapping-title {
  font-weight: 600;
  margin: 0 0 4px;
  color: #333;
}
.mapping-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 2px 0;
}
.mapping-label {
  color: var(--el-color-primary);
  font-weight: 500;
  white-space: nowrap;
}
.mapping-arrow {
  color: #999;
}
.mapping-excerpt {
  flex: 1;
  color: #555;
}
.mapping-score {
  color: #999;
  white-space: nowrap;
}
.query-plan-detail {
  font-size: 13px;
}
.plan-step {
  display: flex;
  gap: 8px;
  align-items: baseline;
  padding: 3px 0;
}
.plan-id {
  background: var(--el-color-primary);
  color: #fff;
  border-radius: 50%;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  flex-shrink: 0;
}
.plan-query {
  flex: 1;
}
.plan-tool {
  color: #999;
  font-size: 12px;
}
.plan-method {
  margin-top: 6px;
  color: #999;
  font-size: 12px;
}
.modular-rag-detail {
  font-size: 13px;
}
.module-tags {
  margin-top: 8px;
  padding: 6px 8px;
  background: #f5f7fa;
  border-radius: 4px;
}
.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}
.module-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 500;
}
.module-tag.activated {
  background: #e1f3d8;
  color: #67c23a;
}
.module-tag.skipped {
  background: #fde2e2;
  color: #909399;
}
.timing-bars {
  margin-top: 8px;
}
.timing-bar-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
}
.timing-label {
  width: 120px;
  font-size: 11px;
  color: #666;
  text-align: right;
  flex-shrink: 0;
}
.timing-bar {
  flex: 1;
  height: 8px;
  background: #ebeef5;
  border-radius: 4px;
  overflow: hidden;
}
.timing-fill {
  height: 100%;
  background: var(--el-color-primary);
  border-radius: 4px;
  transition: width 0.3s;
}
.timing-value {
  width: 50px;
  font-size: 11px;
  color: #999;
}
</style>
