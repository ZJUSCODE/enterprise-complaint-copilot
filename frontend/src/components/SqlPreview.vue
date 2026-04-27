<template>
  <section v-if="sql" class="evidence-block">
    <div class="evidence-head">
      <div>
        <p class="eyebrow">SQL Preview</p>
        <h3>只读查询</h3>
      </div>
      <el-button size="small" @click="copySql">复制</el-button>
    </div>
    <pre class="code-block">{{ sql }}</pre>
  </section>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus';

const props = defineProps<{
  sql?: string;
}>();

async function copySql() {
  if (!props.sql) return;
  await navigator.clipboard.writeText(props.sql);
  ElMessage.success('SQL 已复制');
}
</script>
