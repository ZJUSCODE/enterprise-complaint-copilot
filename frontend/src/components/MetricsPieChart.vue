<template>
  <div ref="chartRef" class="metrics-pie-chart"></div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue';
import * as echarts from 'echarts/core';
import { PieChart } from 'echarts/charts';
import { TooltipComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { MetricItem } from '@/types/api';

echarts.use([PieChart, TooltipComponent, LegendComponent, CanvasRenderer]);

const props = defineProps<{ metrics: MetricItem[] }>();

const chartRef = ref<HTMLDivElement | null>(null);
let chart: echarts.ECharts | null = null;

const COLORS = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#909399', '#b37feb', '#36cfc9'];

function buildOption(metrics: MetricItem[]) {
  const data = metrics
    .filter((m) => typeof m.value === 'number' && m.value > 0)
    .map((m) => ({ name: m.label, value: m.value as number }));
  return {
    color: COLORS,
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} ({d}%)',
    },
    series: [
      {
        type: 'pie',
        radius: ['35%', '65%'],
        center: ['50%', '55%'],
        data,
        label: { show: false },
        emphasis: {
          label: { show: true, fontSize: 14, fontWeight: 'bold' },
          itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0, 0, 0, 0.2)' },
        },
      },
    ],
  };
}

function renderChart() {
  if (!chartRef.value) return;
  const validMetrics = props.metrics.filter((m) => typeof m.value === 'number' && m.value > 0);
  if (validMetrics.length < 2) return;
  if (!chart) {
    chart = echarts.init(chartRef.value);
  }
  chart.setOption(buildOption(props.metrics), true);
}

onMounted(() => {
  renderChart();
  window.addEventListener('resize', () => chart?.resize());
});

onUnmounted(() => {
  chart?.dispose();
  chart = null;
});

watch(() => props.metrics, renderChart, { deep: true });
</script>

<style scoped>
.metrics-pie-chart {
  width: 100%;
  height: 200px;
  margin-top: 8px;
}
</style>
