<template>
  <section v-if="items?.length" class="evidence-block">
    <div class="evidence-head">
      <div>
        <p class="eyebrow">RAG Citations</p>
        <h3>引用依据</h3>
      </div>
      <span>{{ items.length }} 条</span>
    </div>
    <el-collapse class="clean-collapse">
      <el-collapse-item v-for="(item, index) in items" :key="`${item.label}-${index}`" :name="String(index)">
        <template #title>
          <span class="citation-title">{{ item.label }}</span>
        </template>
        <p class="citation-text">{{ item.text }}</p>
        <div class="citation-meta">
          <el-tag v-if="item.source" size="small" effect="plain">{{ item.source }}</el-tag>
          <el-tag v-if="item.retrieval_score !== undefined" size="small" effect="plain">
            retrieval {{ item.retrieval_score }}
          </el-tag>
          <el-tag v-if="item.rerank_score !== undefined" size="small" effect="plain" type="success">
            rerank {{ item.rerank_score }}
          </el-tag>
        </div>
      </el-collapse-item>
    </el-collapse>
  </section>
</template>

<script setup lang="ts">
import type { Citation } from '@/types/api';

defineProps<{
  items?: Citation[];
}>();
</script>
