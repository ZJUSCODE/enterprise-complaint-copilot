<template>
  <div class="page-shell public-page">
    <section class="public-hero">
      <div class="public-hero-copy">
        <p class="eyebrow">智能客诉运营平台</p>
        <h1>让高风险客诉更早被看见</h1>
        <p class="public-lead">
          聚合异常订单与投诉信号，结合只读数据查询和售后 SOP，为运营团队提供有依据、可复核的处置建议。
        </p>
        <div class="mission-actions">
          <RouterLink class="primary-action" to="/login">进入工作台</RouterLink>
          <a class="secondary-action" href="#workflow">查看处理流程</a>
        </div>
      </div>

      <div class="public-principles" aria-label="平台原则">
        <span v-for="item in principles" :key="item">{{ item }}</span>
      </div>
    </section>

    <section id="workflow" class="public-workflow">
      <div class="section-heading">
        <div>
          <p class="eyebrow">处理闭环</p>
          <h2>从风险识别到人工复核，每一步都有依据。</h2>
        </div>
      </div>

      <div class="workflow-list">
        <article v-for="item in workflow" :key="item.step" class="workflow-item">
          <span>{{ item.step }}</span>
          <strong>{{ item.label }}</strong>
          <p>{{ item.helper }}</p>
        </article>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { RouterLink } from 'vue-router';

const principles = ['只读数据边界', 'SOP 引用可追溯', '高风险人工复核'];

const workflow = [
  {
    step: '01',
    label: '发现风险',
    helper: '聚合赔付、评价与投诉类型，优先呈现需要介入的异常。',
  },
  {
    step: '02',
    label: '核验证据',
    helper: '通过受控工具查询订单明细，并关联适用的售后 SOP。',
  },
  {
    step: '03',
    label: '复核留痕',
    helper: '高风险操作进入人工复核，处理依据与执行轨迹全程保留。',
  },
];
</script>
