import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { postChat, streamChat } from '@/api/client';
import { useAuthStore } from '@/stores/auth';
import type { ChatMode, ChatResponse, Role, StreamStatusPayload } from '@/types/api';

export interface ChatMessageState {
  id: string;
  role: 'user' | 'assistant';
  text?: string;
  payload?: ChatResponse;
  createdAt: string;
}

export interface StreamStepState {
  phase: string;
  label: string;
  done: boolean;
}

const PHASE_LABELS: Record<string, string> = {
  routing: '判断目标',
  tools: '准备证据',
  synthesis: '生成结论',
  fallback: '恢复连接',
};

function makeId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function normalizeStatus(payload: StreamStatusPayload): StreamStepState {
  return {
    phase: payload.phase,
    label: PHASE_LABELS[payload.phase] || payload.message || '处理中',
    done: true,
  };
}

export const useChatStore = defineStore('chat', () => {
  const auth = useAuthStore();
  const mode = ref<ChatMode>('auto');
  const role = ref<Role>('analyst');
  const responseLanguage = ref<'auto' | 'zh' | 'en'>('auto');
  const sessionId = ref(localStorage.getItem('copilot_session_id') || '');
  const messages = ref<ChatMessageState[]>([]);
  const isStreaming = ref(false);
  const streamSteps = ref<StreamStepState[]>([]);
  const currentHint = ref('说出要完成的业务目标，系统会自动选择证据链路。');

  const latestAnswer = computed(() => {
    return [...messages.value].reverse().find((item) => item.role === 'assistant' && item.payload)?.payload || null;
  });

  function setMode(nextMode: ChatMode) {
    mode.value = nextMode;
  }

  function rememberSession(payload: ChatResponse) {
    if (payload.session_id) {
      sessionId.value = payload.session_id;
      localStorage.setItem('copilot_session_id', payload.session_id);
    }
  }

  function addAssistant(payload: ChatResponse) {
    messages.value.push({
      id: makeId(),
      role: 'assistant',
      payload,
      createdAt: new Date().toISOString(),
    });
  }

  async function sendMessage(text: string) {
    const message = text.trim();
    if (!message || isStreaming.value) return;

    messages.value.push({
      id: makeId(),
      role: 'user',
      text: message,
      createdAt: new Date().toISOString(),
    });
    isStreaming.value = true;
    streamSteps.value = [];
    currentHint.value = '正在连接流式响应。';

    const request = {
      message,
      mode: mode.value,
      session_id: sessionId.value || null,
      role: (auth.role as Role) || role.value,
      response_language: responseLanguage.value,
    };

    try {
      let payload: ChatResponse;
      try {
        payload = await streamChat(request, {
          onStatus(status) {
            const normalized = normalizeStatus(status);
            streamSteps.value = [...streamSteps.value.filter((item) => item.phase !== normalized.phase), normalized];
            currentHint.value = normalized.label;
          },
        });
      } catch (streamError) {
        streamSteps.value = [
          ...streamSteps.value,
          { phase: 'fallback', label: '流式连接不稳定，正在切换普通响应', done: true },
        ];
        currentHint.value = '正在重试，预计 5 秒内恢复。';
        payload = await postChat(request);
      }

      rememberSession(payload);
      addAssistant(payload);
      currentHint.value = '答案已生成。证据已整理到右侧。';
    } catch (err) {
      addAssistant({
        mode: 'error',
        title: '请求没有完成',
        summary: '后端没有返回可用结果。请确认 FastAPI 服务仍在运行，然后重试。',
        highlights: [err instanceof Error ? err.message : String(err)],
        tool_trace: [],
      });
      currentHint.value = '请求失败，已保留输入内容。';
    } finally {
      isStreaming.value = false;
    }
  }

  return {
    mode,
    role,
    responseLanguage,
    sessionId,
    messages,
    isStreaming,
    streamSteps,
    currentHint,
    latestAnswer,
    setMode,
    sendMessage,
  };
});
