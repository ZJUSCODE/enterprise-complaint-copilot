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
        <el-collapse-item v-if="message.citations?.length" title="SOP 引用" name="citations">
          <RagCitations :items="message.citations" />
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
import type { ChatResponse, TicketRow } from '@/types/api';
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
      message?.estimated_cost_usd !== undefined,
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

function exportTableCsv(table: TicketRow[], requestId?: string) {
  if (!table.length) return;
  const headers = Object.keys(table[0]);
  const csvRows = [headers.join(',')];
  for (const row of table) {
    csvRows.push(headers.map((h) => String(row[h as keyof TicketRow] ?? '')).join(','));
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
</style>
