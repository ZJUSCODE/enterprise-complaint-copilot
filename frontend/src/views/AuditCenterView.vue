<template>
  <div class="page-shell audit-page">
    <section class="audit-hero">
      <div>
        <p class="eyebrow">审计中心</p>
        <h1>每一次 Agent 决策都能回放。</h1>
        <p>按 request_id、路由、工具调用、安全拦截、token/cost 和耗时追踪运行质量。</p>
      </div>
      <button class="secondary-action" type="button" :disabled="store.loading" @click="store.load()">
        刷新
      </button>
    </section>

    <el-alert
      v-if="store.error"
      :title="store.error"
      type="error"
      show-icon
      class="page-alert"
      description="审计日志需要 analyst 或 supervisor 权限。"
    />

    <section class="audit-summary-grid">
      <article v-for="item in summaryCards" :key="item.label" class="metric-card">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <p>{{ item.helper }}</p>
      </article>
    </section>

    <section class="audit-board" v-loading="store.loading">
      <div class="section-heading">
        <div>
          <p class="eyebrow">最近请求</p>
          <h2>运行日志</h2>
        </div>
        <StatusBadge :label="`${store.items.length} 条`" tone="neutral" />
      </div>

      <div v-if="!store.items.length && !store.loading" class="empty-state">
        <p>暂无审计日志。先在处理工作台发送一次请求。</p>
      </div>

      <article v-for="item in store.items" :key="item.request_id" class="audit-item">
        <div class="audit-item-main">
          <div>
            <span class="audit-id">{{ shortId(item.request_id) }}</span>
            <h2>{{ item.response_title || workflowLabel(item.mode) }}</h2>
            <p>{{ item.user_message }}</p>
          </div>
          <div class="audit-tags">
            <el-tag :type="item.blocked_by_guardrail || item.blocked_by_permission ? 'warning' : 'success'" effect="plain">
              {{ item.blocked_by_guardrail || item.blocked_by_permission ? '已拦截' : '已完成' }}
            </el-tag>
            <el-tag effect="plain">{{ workflowLabel(item.route_mode || item.mode) }}</el-tag>
          </div>
        </div>

        <div class="audit-meta">
          <span>{{ item.user_role }}</span>
          <span>{{ Math.round(item.latency_ms || 0) }} ms</span>
          <span>retry {{ item.retry_count }}</span>
          <span>cost ${{ Number(item.estimated_cost_usd || 0).toFixed(6) }}</span>
          <span>{{ item.created_at }}</span>
        </div>

        <el-collapse class="clean-collapse">
          <el-collapse-item title="执行轨迹" name="trace">
            <ToolTrace :items="item.tool_trace" />
          </el-collapse-item>
          <el-collapse-item v-if="item.sql_preview" title="SQL" name="sql">
            <SqlPreview :sql="item.sql_preview" />
          </el-collapse-item>
          <el-collapse-item title="Token / Route" name="runtime">
            <div class="runtime-detail">
              <span v-if="item.token_usage?.total_tokens !== undefined">tokens {{ item.token_usage.total_tokens }}</span>
              <span v-if="item.route_confidence !== null && item.route_confidence !== undefined">confidence {{ item.route_confidence }}</span>
              <span v-if="item.route_source">source {{ item.route_source }}</span>
              <strong v-if="item.trace_id">trace {{ shortId(item.trace_id) }}</strong>
            </div>
            <p v-if="item.route_reason" class="section-copy">{{ item.route_reason }}</p>
          </el-collapse-item>
        </el-collapse>
      </article>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue';
import SqlPreview from '@/components/SqlPreview.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import ToolTrace from '@/components/ToolTrace.vue';
import { useAuditStore } from '@/stores/audit';
import { formatNumber, workflowLabel } from '@/utils/format';

const store = useAuditStore();

const summaryCards = computed(() => {
  const blocked = store.items.filter((item) => item.blocked_by_guardrail || item.blocked_by_permission).length;
  const totalCost = store.items.reduce((sum, item) => sum + Number(item.estimated_cost_usd || 0), 0);
  const avgLatency = store.items.length
    ? Math.round(store.items.reduce((sum, item) => sum + Number(item.latency_ms || 0), 0) / store.items.length)
    : 0;
  return [
    { label: '请求数', value: formatNumber(store.items.length), helper: '最近 50 条运行记录' },
    { label: '安全拦截', value: formatNumber(blocked), helper: 'Guardrail / 权限拒绝' },
    { label: '平均耗时', value: `${avgLatency} ms`, helper: '端到端后端响应' },
    { label: '估算成本', value: `$${totalCost.toFixed(6)}`, helper: 'token 与 embedding 合计' },
  ];
});

function shortId(value?: string | null) {
  if (!value) return '-';
  return value.length > 12 ? `${value.slice(0, 8)}...` : value;
}

onMounted(() => {
  void store.load();
});
</script>
