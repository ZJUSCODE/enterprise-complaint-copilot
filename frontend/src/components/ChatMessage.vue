<template>
  <article class="chat-message" :class="message.role">
    <div class="message-bubble">
      <template v-if="message.role === 'user'">
        <p>{{ message.text }}</p>
      </template>

      <template v-else-if="message.payload">
        <div class="answer-head">
          <div>
            <p class="eyebrow">{{ workflowLabel(message.payload.mode) }}</p>
            <h2>{{ message.payload.title || 'Copilot' }}</h2>
          </div>
          <span v-if="message.payload.latency_ms">{{ Math.round(message.payload.latency_ms) }} ms</span>
        </div>
        <p class="answer-summary" v-html="highlightText(cleanText(message.payload.summary))"></p>

        <div v-if="message.payload.metrics?.length" class="metric-strip">
          <div v-for="metric in message.payload.metrics" :key="metric.label" class="mini-metric">
            <span>{{ metric.label }}</span>
            <strong>{{ metric.value }}</strong>
          </div>
        </div>

        <MetricsPieChart
          v-if="(message.payload.metrics?.length ?? 0) >= 2"
          :metrics="message.payload.metrics ?? []"
        />

        <ul v-if="message.payload.highlights?.length" class="highlight-list">
          <li v-for="item in message.payload.highlights.slice(0, 4)" :key="item" v-html="highlightText(cleanText(item))"></li>
        </ul>

        <el-table v-if="message.payload.table?.length" :data="message.payload.table.slice(0, 5)" size="small" class="result-table">
          <el-table-column prop="order_id" label="订单" min-width="160" />
          <el-table-column prop="category" label="类目" width="110" />
          <el-table-column prop="complaint_type" label="类型" width="130" />
          <el-table-column label="赔付" width="120">
            <template #default="{ row }">{{ formatMoney(row.compensation_amount) }}</template>
          </el-table-column>
        </el-table>

        <div v-if="message.payload.table?.length" class="table-actions">
          <button type="button" class="text-link" @click="exportTableCsv(message.payload.table, message.payload.request_id)">
            导出数据
          </button>
          <button v-if="message.payload.sql_preview" type="button" class="text-link" @click="emit('show-sql')">
            查看底层 SQL 代码
          </button>
        </div>

        <div v-if="message.payload.request_id" class="request-foot">
          request_id: {{ message.payload.request_id }}
        </div>

        <div v-if="message.payload.token_usage || message.payload.estimated_cost_usd !== undefined" class="runtime-meta">
          <span v-if="message.payload.token_usage">{{ tokenLine(message.payload.token_usage) }}</span>
          <span v-if="message.payload.cost_breakdown">
            embedding {{ formatCost(message.payload.cost_breakdown.embedding_cost_usd) }}
            · prompt {{ formatCost(message.payload.cost_breakdown.prompt_cost_usd) }}
            · completion {{ formatCost(message.payload.cost_breakdown.completion_cost_usd) }}
          </span>
          <span v-else-if="message.payload.estimated_cost_usd !== undefined">
            cost {{ formatCost(message.payload.estimated_cost_usd) }}
          </span>
          <span v-if="message.payload.retry_count !== undefined">retry {{ message.payload.retry_count }}</span>
        </div>
      </template>
    </div>
  </article>
</template>

<script setup lang="ts">
import type { ChatMessageState } from '@/stores/chat';
import type { TicketRow, TokenUsage } from '@/types/api';
import { formatMoney, workflowLabel } from '@/utils/format';
import MetricsPieChart from '@/components/MetricsPieChart.vue';

defineProps<{
  message: ChatMessageState;
}>();

const emit = defineEmits<{ (e: 'show-sql'): void }>();

function tokenLine(usage: TokenUsage) {
  const parts = [
    `total ${usage.total_tokens}`,
    `prompt ${usage.prompt_tokens}`,
    `completion ${usage.completion_tokens}`,
  ];
  if (usage.embedding_tokens !== undefined) {
    parts.splice(1, 0, `embedding ${usage.embedding_tokens}`);
  }
  return `tokens ${parts.join(' / ')}`;
}

function formatCost(value?: number) {
  return `$${Number(value || 0).toFixed(6)}`;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function cleanText(value?: string) {
  return escapeHtml(String(value || ''))
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^\s*[-*]\s+/gm, '')
    .trim();
}

function highlightText(input: string): string {
  let result = input;
  result = result.replace(/(\d+(?:\.\d+)?)\s*(元|单|条|笔|%)/g, '<strong>$1$2</strong>');
  result = result.replace(/(3C数码|生鲜|服饰|美妆)/g, '<strong>$1</strong>');
  result = result.replace(/(质量问题|物流延误|包装破损|仅退款)/g, '<strong>$1</strong>');
  result = result.replace(/(人工复核|主管复核|升级|拦截)/g, '<strong>$1</strong>');
  return result;
}

function exportTableCsv(table: TicketRow[], requestId?: string) {
  if (!table.length) return;
  const headers = Object.keys(table[0]) as Array<keyof TicketRow>;
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
</script>

<style scoped>
.answer-summary :deep(strong),
.highlight-list :deep(strong) {
  color: var(--el-color-primary);
  font-weight: 600;
}

.table-actions {
  display: flex;
  gap: 16px;
  margin-top: 8px;
}
.table-actions .text-link {
  background: none;
  border: none;
  color: var(--el-color-primary);
  cursor: pointer;
  font-size: 13px;
  padding: 0;
  text-decoration: underline;
}
.table-actions .text-link:hover {
  color: var(--el-color-primary-light-3);
}
</style>
