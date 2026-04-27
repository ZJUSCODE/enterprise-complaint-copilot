<template>
  <div class="app-shell">
    <header class="topbar">
      <RouterLink class="brand" to="/">
        <span class="brand-mark">C</span>
        <span>
          <strong>Complaint Copilot</strong>
          <small>客诉预警</small>
        </span>
      </RouterLink>
      <nav class="main-nav" aria-label="主导航">
        <RouterLink to="/">今日</RouterLink>
        <RouterLink to="/copilot">处理</RouterLink>
        <RouterLink v-if="canReadAudit" to="/audit">审计</RouterLink>
        <RouterLink v-if="canReadAudit" to="/eval">评测</RouterLink>
        <RouterLink v-if="auth.role === 'supervisor'" to="/review">审批中心</RouterLink>
      </nav>
      <div v-if="auth.user" class="auth-chip">
        <span>{{ auth.user.display_name }}</span>
        <small>{{ auth.user.role }}</small>
        <button type="button" @click="logout">退出</button>
      </div>
    </header>
    <main>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue';
import { RouterLink, RouterView, useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';

const auth = useAuthStore();
const router = useRouter();
const canReadAudit = computed(() => auth.role === 'analyst' || auth.role === 'supervisor');

function logout() {
  auth.logout();
  void router.replace('/login');
}

onMounted(() => {
  void auth.refreshMe();
});
</script>
