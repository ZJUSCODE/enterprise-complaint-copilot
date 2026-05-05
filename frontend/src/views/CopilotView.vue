<template>
  <div class="copilot-page">
    <section class="copilot-main">
      <header class="task-header">
        <div>
          <p class="eyebrow">处理工作台</p>
          <h1>说出目标，系统自动补齐证据。</h1>
          <p>一句话完成查询、SOP 判断和复核流转。需要细节时，再展开右侧证据。</p>
        </div>
        <StatusBadge :label="chat.isStreaming ? '正在处理' : '可提问'" :tone="chat.isStreaming ? 'warn' : 'ok'" />
      </header>

      <form class="ask-panel" @submit.prevent="submit">
        <label for="copilot-draft">今天要完成什么？</label>
        <el-input
          id="copilot-draft"
          v-model="draft"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 5 }"
          resize="none"
          placeholder="例如：质量问题退款超过100元的明细，按 SOP 是否需要主管复核"
          @keydown.enter.exact.prevent="submit"
        />
        <div class="ask-footer">
          <span>{{ activeModeHint }}</span>
          <el-button type="primary" native-type="submit" :loading="chat.isStreaming">发送</el-button>
        </div>
      </form>

      <section class="intent-section" aria-label="常用目标">
        <div class="section-heading compact">
          <div>
            <p class="eyebrow">建议目标</p>
            <h2>不确定怎么问时，从这里开始</h2>
          </div>
        </div>
        <div class="intent-grid">
          <button
            v-for="item in goalCards"
            :key="`${item.mode}-${item.text}`"
            type="button"
            class="intent-card"
            @click="runPrompt(item.mode, item.text)"
          >
            <span>{{ item.kicker }}</span>
            <strong>{{ item.title }}</strong>
            <small>{{ item.helper }}</small>
          </button>
        </div>
      </section>

      <details class="route-settings">
        <summary>高级设置</summary>
        <div class="route-settings-body">
          <div>
            <span>路由</span>
            <el-radio-group :model-value="chat.mode" @change="changeMode">
              <el-radio-button v-for="item in modes" :key="item.value" :value="item.value">
                {{ item.label }}
              </el-radio-button>
            </el-radio-group>
          </div>
          <div>
            <span>回复语言</span>
            <el-select v-model="chat.responseLanguage" class="language-select" size="small">
              <el-option label="自动" value="auto" />
              <el-option label="中文" value="zh" />
              <el-option label="English" value="en" />
            </el-select>
          </div>
        </div>
      </details>

      <div v-if="chat.isStreaming || chat.streamSteps.length" class="stream-status">
        <span>{{ chat.currentHint }}</span>
        <div>
          <el-tag v-for="step in chat.streamSteps" :key="step.phase" effect="plain" :type="step.phase === 'fallback' ? 'warning' : 'success'">
            {{ step.label }}
          </el-tag>
        </div>
      </div>

      <div ref="conversationRef" class="conversation">
        <section v-if="!chat.messages.length" class="empty-conversation">
          <p>输入一个业务目标，或直接选择上方目标开始。</p>
          <button type="button" @click="runPrompt('auto', '请判断今天最需要优先处理的客诉风险，并给出下一步')">
            从今日风险开始
          </button>
        </section>
        <ChatMessage v-for="message in chat.messages" :key="message.id" :message="message" @show-sql="handleShowSql" />
      </div>
    </section>

    <EvidenceRail ref="evidenceRailRef" :message="chat.latestAnswer" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import ChatMessage from '@/components/ChatMessage.vue';
import EvidenceRail from '@/components/EvidenceRail.vue';
import StatusBadge from '@/components/StatusBadge.vue';
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

function handleShowSql() {
  if (evidenceRailRef.value) {
    evidenceRailRef.value.openSqlPanel();
  }
}

const modes: Array<{ value: ChatMode; label: string; hint: string }> = [
  { value: 'auto', label: '自动', hint: '系统会自动判断该查数据、查 SOP，还是走复合链路。' },
  { value: 'function_call_agent', label: '数据', hint: '适合查风险分、退款明细和结构化指标。' },
  { value: 'sql_rag_chain', label: 'SQL + SOP', hint: '先查异常明细，再给出 SOP 依据和升级判断。' },
  { value: 'langchain_rag', label: '政策', hint: '适合只问售后规则、赔付依据和处理口径。' },
  { value: 'router_demo', label: '路由演示', hint: '展示系统如何判断问题类型。' },
];

const goalCards: Array<{ kicker: string; title: string; helper: string; mode: ChatMode; text: string }> = [
  {
    kicker: '数据',
    title: '查高赔付明细',
    helper: '返回异常订单、指标和 SQL 预览',
    mode: 'function_call_agent',
    text: '查一下质量问题退款超过100元的明细',
  },
  {
    kicker: '判断',
    title: '是否需要升级',
    helper: '先查明细，再用 SOP 给出复核建议',
    mode: 'sql_rag_chain',
    text: '质量问题退款超过100元的明细，按 SOP 是否需要主管复核',
  },
  {
    kicker: '订单',
    title: '查订单进展',
    helper: '定位物流状态和下一步处理动作',
    mode: 'auto',
    text: '查询订单 53cdb2fc8bc7dce0b6741e2150273451 的物流状态',
  },
  {
    kicker: '规则',
    title: '查售后口径',
    helper: '只返回可引用的 SOP 依据',
    mode: 'langchain_rag',
    text: '3C 数码拆封后出现质量问题，应该怎么处理',
  },
];

const activeModeHint = computed(() => modes.find((item) => item.value === chat.mode)?.hint || modes[0].hint);

function changeMode(value: string | number | boolean | undefined) {
  chat.setMode(value as ChatMode);
}

async function submit() {
  const text = draft.value.trim();
  if (!text) return;
  draft.value = '';
  await chat.sendMessage(text);
}

async function runPrompt(mode: ChatMode, text: string) {
  chat.setMode(mode);
  draft.value = '';
  await chat.sendMessage(text);
}

watch(
  () => chat.messages.length,
  async () => {
    await nextTick();
    if (conversationRef.value) {
      conversationRef.value.scrollTop = conversationRef.value.scrollHeight;
    }
  },
);

onMounted(async () => {
  if (!appStore.sampleQuestions.length) {
    await appStore.loadDashboard();
  }

  const queryMode = route.query.mode;
  const queryPrompt = route.query.prompt;
  if (!consumedQuery.value && typeof queryMode === 'string' && typeof queryPrompt === 'string') {
    consumedQuery.value = true;
    chat.setMode(queryMode as ChatMode);
    if (route.query.run === '1') {
      await chat.sendMessage(queryPrompt);
    } else {
      draft.value = queryPrompt;
    }
  }
});
</script>
