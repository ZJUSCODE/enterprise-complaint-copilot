<template>
  <section class="chart-grid" aria-label="风险趋势">
    <div class="chart-panel wide">
      <div class="panel-head">
        <div>
          <p class="eyebrow">近 30 日异常</p>
          <h2>{{ periodBadCount }} 单</h2>
        </div>
        <span>{{ trendRange }}</span>
      </div>
      <div ref="trendRef" class="chart-box" />
    </div>
  </section>
</template>

<script setup lang="ts">
import { LineChart } from 'echarts/charts';
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { init, use, type ECharts } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import type { OverviewResponse } from '@/types/api';

const props = defineProps<{
  overview: OverviewResponse;
}>();

const trendRef = ref<HTMLDivElement | null>(null);
use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

let trendChart: ECharts | null = null;

const periodBadCount = computed(() => props.overview.trend.reduce((sum, item) => sum + item.bad, 0));
const trendRange = computed(() => {
  const start = props.overview.trend_window_start || props.overview.trend[0]?.date;
  const end = props.overview.trend_window_end || props.overview.trend[props.overview.trend.length - 1]?.date;
  if (!start || !end) return '无趋势数据';
  return `${start.slice(5).replace('-', '/')} - ${end.slice(5).replace('-', '/')}`;
});

function renderCharts() {
  if (!trendRef.value) return;
  trendChart?.dispose();

  trendChart = init(trendRef.value);

  trendChart.setOption({
    color: ['#0b6b57', '#2563eb'],
    tooltip: { trigger: 'axis' },
    legend: { top: 0, right: 0, textStyle: { color: '#5f6368' } },
    grid: { left: 36, right: 18, top: 38, bottom: 32 },
    xAxis: {
      type: 'category',
      data: props.overview.trend.map((item) => item.date),
      axisLabel: { color: '#5f6368' },
      axisLine: { lineStyle: { color: '#d9e1e4' } },
    },
    yAxis: {
      type: 'value',
      name: '单',
      nameTextStyle: { color: '#5f6368', padding: [0, 0, 0, -18] },
      axisLabel: { color: '#5f6368', formatter: '{value} 单' },
      splitLine: { lineStyle: { color: '#e6ecef' } },
    },
    series: [
      {
        name: '异常订单',
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: props.overview.trend.map((item) => item.bad),
      },
      {
        name: '总订单',
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: props.overview.trend.map((item) => item.total),
      },
    ],
  });
}

function resizeCharts() {
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
  trendChart?.dispose();
});
</script>
