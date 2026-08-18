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
        <div v-if="item.structured_output" class="structured-output">
          <div v-for="(val, key) in item.structured_output" :key="String(key)" class="so-row">
            <span class="so-key">{{ key }}</span>
            <span class="so-val">{{ typeof val === 'object' ? JSON.stringify(val) : String(val ?? '') }}</span>
          </div>
        </div>
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

<style scoped>
.structured-output {
  margin: 6px 0;
  padding: 6px 8px;
  background: #f5f7fa;
  border-radius: 4px;
  font-size: 12px;
}
.so-row {
  display: flex;
  gap: 8px;
  padding: 2px 0;
}
.so-key {
  color: #666;
  min-width: 100px;
}
.so-val {
  font-weight: 500;
  word-break: break-all;
}
</style>
