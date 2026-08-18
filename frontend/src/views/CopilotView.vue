<template>
  <div class="copilot-page">
    <section class="copilot-main">
      <header class="copilot-toolbar">
        <div>
          <h1>智能处理</h1>
          <p>查询数据、核对规则并生成下一步建议</p>
        </div>
        <div class="model-indicator">
          <span class="live-dot" />
          <span>{{ appStore.overview?.llm_model || 'Terra' }}</span>
        </div>
      </header>

      <div class="mode-tabs" aria-label="处理模式">
        <button
          v-for="item in modes"
          :key="item.value"
          type="button"
          :class="{ active: chat.mode === item.value }"
          @click="chat.setMode(item.value)"
        >
          {{ item.label }}
        </button>
      </div>

      <div ref="conversationRef" class="conversation">
        <section v-if="!chat.messages.length" class="empty-conversation">
          <ChatLineRound />
          <h2>输入一个客诉处理目标</h2>
          <p>系统会自动选择 Agent、Text-to-SQL 或 SOP 链路。</p>
          <div class="prompt-list">
            <button v-for="item in goalCards" :key="item.text" type="button" @click="runPrompt(item.mode, item.text)">
              <span>{{ item.title }}</span>
              <ArrowRight />
            </button>
          </div>
        </section>

        <ChatMessage v-for="message in chat.messages" :key="message.id" :message="message" @show-sql="handleShowSql" />

        <section v-if="chat.isStreaming" class="agent-running" aria-live="polite">
          <span class="spinner" />
          <div>
            <strong>{{ chat.currentHint }}</strong>
            <p>已运行 {{ chat.elapsedSeconds }} 秒，完成后会显示模型调用、SQL 与 SOP 证据。</p>
          </div>
        </section>
      </div>

      <button
        type="button"
        class="mobile-evidence-trigger"
        :aria-expanded="mobileEvidenceOpen"
        aria-controls="mobile-evidence-panel"
        @click="mobileEvidenceOpen = true"
      >
        <DocumentChecked />
        <span>本轮证据</span>
        <small>{{ evidenceSummary }}</small>
        <ArrowUp />
      </button>

      <form class="composer" @submit.prevent="submit">
        <el-input
          id="copilot-draft"
          v-model="draft"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 5 }"
          resize="none"
          placeholder="描述要查询的客诉问题或处理目标"
          aria-label="客诉处理目标"
          @keydown.enter.exact.prevent="submit"
        />
        <div class="composer-footer">
          <span>{{ activeModeHint }}</span>
          <button class="send-button" type="submit" :disabled="chat.isStreaming || !draft.trim()" title="发送">
            <Promotion />
          </button>
        </div>
      </form>
    </section>

    <button
      v-if="mobileEvidenceOpen"
      type="button"
      class="evidence-backdrop"
      aria-label="点击遮罩关闭证据抽屉"
      @click="mobileEvidenceOpen = false"
    />
    <div
      id="mobile-evidence-panel"
      class="evidence-drawer"
      :class="{ open: mobileEvidenceOpen }"
      :role="isMobileViewport ? 'dialog' : 'complementary'"
      aria-label="本轮证据"
      :aria-modal="isMobileViewport && mobileEvidenceOpen ? 'true' : undefined"
      :inert="isMobileViewport && !mobileEvidenceOpen"
    >
      <button type="button" class="evidence-drawer-close" title="关闭证据抽屉" @click="mobileEvidenceOpen = false">
        <Close />
      </button>
      <EvidenceRail ref="evidenceRailRef" :message="chat.latestAnswer" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ArrowRight, ArrowUp, ChatLineRound, Close, DocumentChecked, Promotion } from '@element-plus/icons-vue';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import ChatMessage from '@/components/ChatMessage.vue';
import EvidenceRail from '@/components/EvidenceRail.vue';
import { useAppStore } from '@/stores/app';
import { useChatStore } from '@/stores/chat';
import type { ChatMode } from '@/types/api';

const route = useRoute();
const appStore = useAppStore();
const chat = useChatStore();
const draft = ref('');
const conversationRef = ref<HTMLDivElement | null>(null);
const consumedQuery = ref(false);
const evidenceRailRef = ref<InstanceType<typeof EvidenceRail> | null>(null);
const mobileEvidenceOpen = ref(false);
const isMobileViewport = ref(false);
let mobileMedia: MediaQueryList | null = null;

function syncMobileViewport() {
  isMobileViewport.value = Boolean(mobileMedia?.matches);
  if (!isMobileViewport.value) mobileEvidenceOpen.value = false;
}

const modes: Array<{ value: ChatMode; label: string; hint: string }> = [
  { value: 'auto', label: '自动判断', hint: 'Terra 先判断任务，再选择合适链路' },
  { value: 'function_call_agent', label: 'Agent 查询', hint: 'Terra 选择工具并生成只读数据查询' },
  { value: 'sql_rag_chain', label: 'SQL + SOP', hint: 'Terra 解析查询条件并基于 SOP 生成结论' },
  { value: 'langchain_rag', label: '政策问答', hint: '检索本地 SOP，再由 Terra 基于证据回答' },
];

const goalCards: Array<{ title: string; mode: ChatMode; text: string }> = [
  { title: '查询高赔付质量问题明细', mode: 'function_call_agent', text: '查一下质量问题退款超过100元的明细' },
  { title: '判断异常客诉是否需要主管复核', mode: 'sql_rag_chain', text: '质量问题退款超过100元的明细，按 SOP 是否需要主管复核' },
  { title: '查询 3C 数码拆封后的售后口径', mode: 'langchain_rag', text: '3C 数码拆封后出现质量问题，应该怎么处理' },
];

const activeModeHint = computed(() => modes.find((item) => item.value === chat.mode)?.hint || modes[0].hint);
const evidenceSummary = computed(() => {
  const answer = chat.latestAnswer;
  if (!answer) return '提问后生成';
  const labels = [
    answer.sql_preview ? 'SQL' : '',
    answer.citations?.length ? `${answer.citations.length} 条引用` : '',
    answer.tool_trace?.length ? '执行轨迹' : '',
  ].filter(Boolean);
  return labels.join(' · ') || '暂无明细';
});

async function handleShowSql() {
  mobileEvidenceOpen.value = true;
  await nextTick();
  evidenceRailRef.value?.openSqlPanel();
}

async function submit() {
  const text = draft.value.trim();
  if (!text) return;
  draft.value = '';
  await chat.sendMessage(text);
}

async function runPrompt(mode: ChatMode, text: string) {
  chat.setMode(mode);
  await chat.sendMessage(text);
}

watch(() => chat.messages.length, async () => {
  await nextTick();
  if (conversationRef.value) conversationRef.value.scrollTop = conversationRef.value.scrollHeight;
});

onMounted(async () => {
  mobileMedia = window.matchMedia('(max-width: 820px)');
  syncMobileViewport();
  mobileMedia.addEventListener('change', syncMobileViewport);
  if (!appStore.overview) await appStore.loadDashboard();
  const queryMode = route.query.mode;
  const queryPrompt = route.query.prompt;
  if (!consumedQuery.value && typeof queryMode === 'string' && typeof queryPrompt === 'string') {
    consumedQuery.value = true;
    chat.setMode(queryMode as ChatMode);
    if (route.query.run === '1') await chat.sendMessage(queryPrompt);
    else draft.value = queryPrompt;
  }
});

onBeforeUnmount(() => {
  mobileMedia?.removeEventListener('change', syncMobileViewport);
});
</script>
