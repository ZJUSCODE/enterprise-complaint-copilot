<template>
  <section class="section-block">
    <div class="section-heading">
      <div>
        <p class="eyebrow">只读数据边界</p>
        <h2>{{ table?.name || 'tickets' }}</h2>
      </div>
      <StatusBadge label="SELECT / WITH" tone="ok" />
    </div>

    <p class="section-copy">{{ table?.description }}</p>

    <el-collapse v-model="activeNames" class="clean-collapse">
      <el-collapse-item title="业务口径" name="metrics">
        <div class="schema-chip-row">
          <span v-for="metric in schema.metrics" :key="metric.name" class="schema-chip">
            {{ metric.name }} = {{ metric.expression }}
          </span>
        </div>
      </el-collapse-item>
      <el-collapse-item title="可筛选字段" name="columns">
        <el-table :data="table?.columns || []" size="small" class="schema-table">
          <el-table-column prop="name" label="字段" min-width="150" />
          <el-table-column prop="type" label="类型" width="120" />
          <el-table-column prop="description" label="说明" min-width="260" />
          <el-table-column label="用途" width="160">
            <template #default="{ row }">
              <el-tag v-if="row.filterable" size="small" effect="plain">可筛选</el-tag>
              <el-tag v-if="row.dimension" size="small" effect="plain" type="success">维度</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-collapse-item>
      <el-collapse-item title="安全校验" name="safety">
        <p class="section-copy">
          {{ schema.safety.validator }} 只允许 {{ schema.safety.allowed_statements.join(' / ') }}，
          写操作关键字会在工具层拒绝。
        </p>
      </el-collapse-item>
    </el-collapse>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import StatusBadge from '@/components/StatusBadge.vue';
import type { SchemaCatalog } from '@/types/api';

const props = defineProps<{
  schema: SchemaCatalog;
}>();

const activeNames = ref(['metrics']);
const table = computed(() => props.schema.tables[0]);
</script>
