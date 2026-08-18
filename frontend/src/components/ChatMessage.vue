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
        <p
          class="answer-summary"
          v-html="highlightText(cleanText(message.payload.summary, Boolean(message.payload.table?.length)))"
        ></p>

        <div v-if="message.payload.metrics?.length" class="metric-strip">
          <div v-for="metric in message.payload.metrics" :key="metric.label" class="mini-metric">
            <span>{{ metric.label }}</span>
            <strong>{{ displayMetric(metric.label, metric.value) }}</strong>
          </div>
        </div>

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

        <div v-if="message.payload.table?.length || message.payload.sql_preview" class="table-actions">
          <button
            v-if="message.payload.table?.length"
            type="button"
            class="text-link"
            @click="exportTableCsv(message.payload.table, message.payload.request_id)"
          >
            导出数据
          </button>
          <button v-if="message.payload.sql_preview" type="button" class="text-link" @click="emit('show-sql')">
            查看底层 SQL
          </button>
        </div>

        <div v-if="message.payload.request_id" class="request-foot">
          request_id: {{ message.payload.request_id }}
        </div>

      </template>
    </div>
  </article>
</template>

<script setup lang="ts">
import type { ChatMessageState } from '@/stores/chat';
import type { TicketRow } from '@/types/api';
import { formatMoney, workflowLabel } from '@/utils/format';

defineProps<{
  message: ChatMessageState;
}>();

const emit = defineEmits<{ (e: 'show-sql'): void }>();

function displayMetric(label: string, value: string | number) {
  if (typeof value !== 'number') return value;
  if (label.includes('金额') || label.includes('赔付') || label.includes('实付')) return formatMoney(value);
  if (label.includes('工单') || label.includes('订单') || label.includes('触发')) return `${value} 单`;
  return value;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function cleanText(value?: string, stripMarkdownTables = false) {
  const lines = String(value || '').split('\n');
  const normalized = (stripMarkdownTables
    ? lines.filter((line) => {
        const trimmed = line.trim();
        return !(trimmed.startsWith('|') && trimmed.endsWith('|') && trimmed.split('|').length >= 4);
      })
    : lines
  ).join('\n');

  return escapeHtml(normalized)
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^\s*#{1,6}\s+/gm, '')
    .replace(/^\s*[-*]\s+/gm, '• ')
    .replace(/\n{3,}/g, '\n\n')
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
