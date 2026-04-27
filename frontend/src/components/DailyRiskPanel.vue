<template>
  <section class="section-block">
    <div class="section-heading">
      <div>
        <p class="eyebrow">今日动作</p>
        <h2>{{ report.headline }}</h2>
      </div>
      <StatusBadge :label="report.delivery_mock.schedule || 'daily 09:30'" tone="neutral" />
    </div>

    <div class="metric-strip">
      <div v-for="metric in report.metrics" :key="metric.label" class="mini-metric">
        <span>{{ metric.label }}</span>
        <strong>{{ metric.value }}</strong>
      </div>
    </div>

    <div class="risk-action-grid">
      <div class="risk-list">
        <h3>优先处理</h3>
        <article v-for="risk in report.top_risks.slice(0, 4)" :key="`${risk.category}-${risk.complaint_type}`" class="risk-row">
          <div>
            <strong>{{ risk.category }} / {{ risk.complaint_type }}</strong>
            <span>{{ risk.order_count }} 单，赔付 {{ formatMoney(risk.compensation_total) }}</span>
          </div>
          <el-progress :percentage="risk.share" :stroke-width="8" color="#c92a2a" :show-text="false" />
        </article>
        <p v-if="!report.top_risks.length" class="muted">今日没有命中异常风险。</p>
      </div>

      <div class="action-list">
        <h3>下一步</h3>
        <ol>
          <li v-for="action in report.recommended_actions" :key="action">{{ action }}</li>
        </ol>
        <p class="muted">{{ report.delivery_mock.note }}</p>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import StatusBadge from '@/components/StatusBadge.vue';
import type { DailyRiskReport } from '@/types/api';
import { formatMoney } from '@/utils/format';

defineProps<{
  report: DailyRiskReport;
}>();
</script>
