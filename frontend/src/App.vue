<template>
  <div class="app-shell" :class="{ 'has-navigation': auth.user }">
    <aside v-if="auth.user" class="side-nav" :class="{ open: mobileOpen }">
      <div class="side-brand">
        <span class="brand-mark">C</span>
        <span>
          <strong>客诉 Copilot</strong>
          <small>运营工作台</small>
        </span>
        <button class="icon-button side-close" type="button" title="关闭导航" @click="mobileOpen = false">
          <Close />
        </button>
      </div>

      <nav class="side-links" aria-label="主导航">
        <RouterLink to="/">
          <DataAnalysis />
          <span>今日总览</span>
        </RouterLink>
        <RouterLink to="/copilot">
          <ChatLineRound />
          <span>智能处理</span>
        </RouterLink>
        <RouterLink v-if="canReadAudit" to="/audit">
          <DocumentChecked />
          <span>调用审计</span>
        </RouterLink>
        <RouterLink v-if="auth.role === 'supervisor'" to="/review">
          <CircleCheck />
          <span>人工复核</span>
        </RouterLink>
      </nav>

      <div class="side-status">
        <span class="live-dot" />
        <span>Terra 服务在线</span>
      </div>

      <div class="side-user">
        <span class="user-avatar">{{ auth.user.display_name.slice(0, 1) }}</span>
        <span>
          <strong>{{ auth.user.display_name }}</strong>
          <small>{{ roleLabel }}</small>
        </span>
        <button class="icon-button" type="button" title="退出登录" @click="logout">
          <SwitchButton />
        </button>
      </div>
    </aside>

    <header v-if="auth.user" class="mobile-header">
      <button class="icon-button" type="button" title="打开导航" @click="mobileOpen = true"><Menu /></button>
      <strong>客诉 Copilot</strong>
      <span class="live-dot" />
    </header>

    <button v-if="auth.user && mobileOpen" class="nav-backdrop" type="button" aria-label="关闭导航" @click="mobileOpen = false" />

    <main class="app-main">
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ChatLineRound, CircleCheck, Close, DataAnalysis, DocumentChecked, Menu, SwitchButton } from '@element-plus/icons-vue';
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const mobileOpen = ref(false);
const canReadAudit = computed(() => auth.role === 'analyst' || auth.role === 'supervisor');
const roleLabel = computed(() => ({ viewer: '只读查看', analyst: '运营分析', supervisor: '复核主管' }[auth.role] || auth.role));

watch(() => route.fullPath, () => {
  mobileOpen.value = false;
});

function logout() {
  auth.logout();
  void router.replace('/login');
}
</script>
