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
        <p class="answer-summary">{{ cleanText(message.payload.summary) }}</p>

        <div v-if="message.payload.metrics?.length" class="metric-strip">
          <div v-for="metric in message.payload.metrics" :key="metric.label" class="mini-metric">
            <span>{{ metric.label }}</span>
            <strong>{{ metric.value }}</strong>
          </div>
        </div>

        <ul v-if="message.payload.highlights?.length" class="highlight-list">
          <li v-for="item in message.payload.highlights.slice(0, 4)" :key="item">{{ cleanText(item) }}</li>
        </ul>

        <el-table v-if="message.payload.table?.length" :data="message.payload.table.slice(0, 5)" size="small" class="result-table">
          <el-table-column prop="order_id" label="订单" min-width="160" />
          <el-table-column prop="category" label="类目" width="110" />
          <el-table-column prop="complaint_type" label="类型" width="130" />
          <el-table-column label="赔付" width="120">
            <template #default="{ row }">{{ formatMoney(row.compensation_amount) }}</template>
          </el-table-column>
        </el-table>

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
import type { TokenUsage } from '@/types/api';
import { formatMoney, workflowLabel } from '@/utils/format';

defineProps<{
  message: ChatMessageState;
}>();

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

function cleanText(value?: string) {
  return String(value || '')
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^\s*[-*]\s+/gm, '')
    .trim();
}
</script>
