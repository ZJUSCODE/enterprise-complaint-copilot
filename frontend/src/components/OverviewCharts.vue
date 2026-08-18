<template>
  <section class="chart-grid" aria-label="风险趋势">
    <div class="chart-panel">
      <div class="panel-head">
        <div>
          <p class="eyebrow">风险占比</p>
          <h2>{{ formatPercent(overview.risk_rate) }}</h2>
        </div>
        <span>{{ overview.high_risk_cnt }} / {{ overview.total_users }} 用户</span>
      </div>
      <div ref="riskRef" class="chart-box" />
    </div>
    <div class="chart-panel wide">
      <div class="panel-head">
        <div>
          <p class="eyebrow">近 30 日异常</p>
          <h2>{{ latestBadCount }} 单</h2>
        </div>
        <span>{{ overview.latest_snapshot }}</span>
      </div>
      <div ref="trendRef" class="chart-box" />
    </div>
  </section>
</template>

<script setup lang="ts">
import { LineChart, PieChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { init, use, type ECharts } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import type { OverviewResponse } from '@/types/api';
import { formatPercent } from '@/utils/format';

const props = defineProps<{
  overview: OverviewResponse;
}>();

const riskRef = ref<HTMLDivElement | null>(null);
const trendRef = ref<HTMLDivElement | null>(null);
use([PieChart, LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

let riskChart: ECharts | null = null;
let trendChart: ECharts | null = null;

const latestBadCount = computed(() => props.overview.trend[props.overview.trend.length - 1]?.bad || 0);

function renderCharts() {
  if (!riskRef.value || !trendRef.value) return;
  riskChart?.dispose();
  trendChart?.dispose();

  riskChart = init(riskRef.value);
  trendChart = init(trendRef.value);

  const highRisk = props.overview.high_risk_cnt;
  const others = Math.max(props.overview.total_users - highRisk, 0);

  riskChart.setOption({
    color: ['#c92a2a', '#dfe8ea'],
    tooltip: { trigger: 'item' },
    series: [
      {
        type: 'pie',
        radius: ['62%', '82%'],
        avoidLabelOverlap: true,
        label: { color: '#202124' },
        data: [
          { value: highRisk, name: '高风险' },
          { value: others, name: '其他用户' },
        ],
      },
    ],
  });

  trendChart.setOption({
    color: ['#0b6b57', '#2563eb'],
    tooltip: { trigger: 'axis' },
    grid: { left: 36, right: 18, top: 28, bottom: 32 },
    xAxis: {
      type: 'category',
      data: props.overview.trend.map((item) => item.date),
      axisLabel: { color: '#5f6368' },
      axisLine: { lineStyle: { color: '#d9e1e4' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#5f6368' },
      splitLine: { lineStyle: { color: '#e6ecef' } },
    },
    series: [
      {
        name: '异常评价',
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: props.overview.trend.map((item) => item.bad),
      },
      {
        name: '订单量',
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: props.overview.trend.map((item) => item.total),
      },
    ],
  });
}

function resizeCharts() {
  riskChart?.resize();
  trendChart?.resize();
}

watch(
  () => props.overview,
  async () => {
    await nextTick();
    renderCharts();
  },
  { immediate: true, deep: true },
);

window.addEventListener('resize', resizeCharts);

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeCharts);
  riskChart?.dispose();
  trendChart?.dispose();
});
</script>
