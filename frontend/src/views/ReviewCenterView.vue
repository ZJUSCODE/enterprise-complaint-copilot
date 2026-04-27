<template>
  <div class="page-shell review-page">
    <section class="review-hero">
      <div>
        <p class="eyebrow">审批中心</p>
        <h1>先处理待复核，再回看历史。</h1>
        <p>高危退款、改单和越权请求只在这里做人工确认，不会触发真实业务写入。</p>
      </div>
      <button class="secondary-action" type="button" :disabled="store.loading" @click="store.createDemoCase">
        生成演示复核单
      </button>
    </section>

    <el-alert
      v-if="store.error"
      :title="store.error"
      type="error"
      show-icon
      class="page-alert"
      description="正在保留队列筛选。请确认当前角色具备 supervisor 权限。"
    />

    <div class="review-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.value"
        type="button"
        :class="{ active: store.status === tab.value }"
        @click="store.loadQueue(tab.value)"
      >
        <strong>{{ tab.label }}</strong>
        <span>{{ tab.helper }}</span>
      </button>
    </div>

    <div v-loading="store.loading" class="review-list">
      <section v-if="!store.items.length" class="empty-state">
        <p>{{ emptyText }}</p>
        <button v-if="store.status === 'pending'" class="primary-action" type="button" @click="store.createDemoCase">生成一条待审样例</button>
      </section>

      <article v-for="item in store.items" :key="item.case_id" class="review-item">
        <div class="review-item-head">
          <div>
            <span>{{ item.case_id }}</span>
            <h2>{{ item.reason || '需要人工复核' }}</h2>
          </div>
          <el-tag :type="statusTagType(item.status)" effect="plain">{{ reviewStatusLabel(item.status) }}</el-tag>
        </div>

        <div class="review-meta">
          <span>来源 {{ item.source_mode || '-' }}</span>
          <span>角色 {{ item.user_role || '-' }}</span>
          <span>优先级 {{ item.case_priority || 'medium' }}</span>
          <span>负责人 {{ item.assignee || 'supervisor_queue' }}</span>
        </div>

        <p class="review-message">{{ item.user_message }}</p>
        <p v-if="item.response_summary" class="review-summary">{{ item.response_summary }}</p>

        <el-collapse v-if="item.tool_trace?.length" class="clean-collapse">
          <el-collapse-item title="查看执行轨迹" name="trace">
            <ToolTrace :items="item.tool_trace" />
          </el-collapse-item>
        </el-collapse>

        <div v-if="item.status === 'pending'" class="review-actions">
          <button class="primary-action" type="button" @click="decide(item, 'resolved')">通过</button>
          <button class="secondary-action danger" type="button" @click="decide(item, 'rejected')">驳回</button>
        </div>
        <p v-else-if="item.reviewer_note" class="review-note">{{ item.reviewer_note }}</p>
      </article>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import ToolTrace from '@/components/ToolTrace.vue';
import { useReviewStore } from '@/stores/review';
import type { ReviewCase, ReviewStatus } from '@/types/api';
import { reviewStatusLabel } from '@/utils/format';

const store = useReviewStore();

const tabs: Array<{ value: ReviewStatus; label: string; helper: string }> = [
  { value: 'pending', label: '待复核', helper: '先处理' },
  { value: 'resolved', label: '已通过', helper: '可追溯' },
  { value: 'rejected', label: '已驳回', helper: '看原因' },
];

const emptyText = computed(() => {
  if (store.status === 'pending') return '当前没有待复核单。需要演示时可以生成一条样例。';
  return `当前没有${reviewStatusLabel(store.status)}记录。`;
});

function statusTagType(status: ReviewStatus) {
  if (status === 'resolved') return 'success';
  if (status === 'rejected') return 'danger';
  return 'warning';
}

async function decide(item: ReviewCase, status: ReviewStatus) {
  const defaults: Record<ReviewStatus, string> = {
    resolved: '已确认进入线下处理，不执行自动退款或改单。',
    rejected: '证据不足，驳回本次高风险处理请求。',
    pending: '',
  };
  try {
    const result = await ElMessageBox.prompt('填写处理说明', reviewStatusLabel(status), {
      confirmButtonText: '提交',
      cancelButtonText: '取消',
      inputValue: defaults[status],
      inputType: 'textarea',
    });
    await store.decide(item.case_id, status, result.value);
    ElMessage.success('状态已更新');
  } catch (err) {
    if (err !== 'cancel') {
      ElMessage.error(err instanceof Error ? err.message : String(err));
    }
  }
}

onMounted(() => {
  void store.loadQueue();
});
</script>
