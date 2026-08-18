<template>
  <section class="agent-flow">
    <div class="evidence-head">
      <div>
        <p class="eyebrow">Agent 执行链路</p>
        <h3>{{ message.route?.mode || message.mode }}</h3>
      </div>
      <span v-if="message.trace_id">{{ shortId(message.trace_id) }}</span>
    </div>

    <div class="flow-steps">
      <article v-for="step in steps" :key="step.key" class="flow-step" :class="step.state">
        <div class="flow-dot" />
        <div>
          <strong>{{ step.label }}</strong>
          <p>{{ step.detail }}</p>
        </div>
      </article>
    </div>

    <div class="flow-meta">
      <span v-if="message.latency_ms !== undefined">{{ Math.round(message.latency_ms) }} ms</span>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { ChatResponse } from '@/types/api';
import { workflowLabel } from '@/utils/format';

const props = defineProps<{
  message: ChatResponse;
}>();

type FlowStepState = 'done' | 'warn' | 'idle';

interface FlowStep {
  key: string;
  label: string;
  detail: string;
  state: FlowStepState;
}

const steps = computed<FlowStep[]>(() => {
  const message = props.message;
  const guarded = message.mode === 'guardrail' || Boolean(message.review_case);
  const blocked = message.mode === 'guardrail';
  const routeLabel = message.route?.mode ? workflowLabel(message.route.mode) : workflowLabel(message.mode);

  return [
    {
      key: 'permission',
      label: '权限',
      detail: message.review_case?.user_role ? `角色 ${message.review_case.user_role}` : 'Bearer Token / RBAC 已校验',
      state: 'done',
    },
    {
      key: 'guardrail',
      label: '安全策略',
      detail: blocked ? '命中高危操作，停止自动执行' : '未命中退款、改单、导出等高危动作',
      state: blocked ? 'warn' : 'done',
    },
    {
      key: 'router',
      label: '路由',
      detail: message.route?.reason || `进入 ${routeLabel}`,
      state: blocked ? 'idle' : 'done',
    },
    {
      key: 'tools',
      label: '工具 / 检索',
      detail: toolDetail(message),
      state: message.tool_trace?.length || message.citations?.length || message.sql_preview ? 'done' : blocked ? 'idle' : 'warn',
    },
    {
      key: 'review',
      label: '人工复核',
      detail: guarded ? message.review_case?.reason || message.review_reason || '已写入复核队列' : '无需复核，保留审计记录',
      state: guarded ? 'warn' : 'done',
    },
    {
      key: 'audit',
      label: '审计',
      detail: message.request_id ? `request_id ${shortId(message.request_id)}` : '请求已完成',
      state: 'done',
    },
  ];
});

function toolDetail(message: ChatResponse) {
  const tools = message.tool_trace?.map((item) => item.tool).filter(Boolean) || [];
  if (tools.length) return tools.join(' -> ');
  if (message.sql_preview) return '只读 SQL 已生成';
  if (message.citations?.length) return `${message.citations.length} 条 SOP 引用`;
  return '本轮没有调用外部工具';
}

function shortId(value?: string | null) {
  if (!value) return '-';
  return value.length > 10 ? `${value.slice(0, 8)}...` : value;
}
</script>
