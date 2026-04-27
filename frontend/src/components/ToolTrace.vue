<template>
  <section v-if="items?.length" class="evidence-block">
    <div class="evidence-head">
      <div>
        <p class="eyebrow">Tool Trace</p>
        <h3>执行轨迹</h3>
      </div>
      <span>{{ items.length }} 步</span>
    </div>
    <el-timeline>
      <el-timeline-item v-for="(item, index) in items" :key="`${item.tool}-${index}`" :timestamp="`Step ${index + 1}`">
        <strong>{{ item.tool }}</strong>
        <p>{{ item.result_summary || '已执行' }}</p>
        <details v-if="item.arguments">
          <summary>参数</summary>
          <pre class="code-block compact">{{ JSON.stringify(item.arguments, null, 2) }}</pre>
        </details>
      </el-timeline-item>
    </el-timeline>
  </section>
</template>

<script setup lang="ts">
import type { ToolTraceItem } from '@/types/api';

defineProps<{
  items?: ToolTraceItem[];
}>();
</script>
