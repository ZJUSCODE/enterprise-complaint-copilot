<template>
  <div class="login-page">
    <section class="login-intro">
      <div class="login-brand">
        <span class="brand-mark inverse">C</span>
        <strong>客诉 Copilot</strong>
      </div>
      <div>
        <h1>让每次客诉处理，都有数据和规则依据。</h1>
        <p>统一查询异常工单、售后 SOP 与人工复核记录。</p>
      </div>
      <div class="login-system-status">
        <span><i class="live-dot" /> Terra 已连接</span>
        <span>只读数据访问</span>
      </div>
    </section>

    <section class="login-form-area">
      <div class="login-panel">
        <div class="login-copy">
          <h2>登录工作台</h2>
          <p>选择演示权限，账号会自动填充。</p>
        </div>

        <el-alert v-if="auth.error" :title="auth.error" type="error" show-icon />

        <div class="role-segment" aria-label="演示权限">
          <button
            v-for="item in roleOptions"
            :key="item.username"
            type="button"
            :class="{ active: username === item.username }"
            @click="fill(item.username, item.password)"
          >
            {{ item.label }}
          </button>
        </div>

        <el-form class="login-form" label-position="top" @submit.prevent="submit">
          <el-form-item label="账号">
            <el-input v-model="username" autocomplete="username" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="password" type="password" autocomplete="current-password" show-password />
          </el-form-item>
          <el-button type="primary" native-type="submit" :loading="auth.loading">进入工作台</el-button>
        </el-form>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';

const auth = useAuthStore();
const router = useRouter();
const route = useRoute();
const username = ref('analyst@example.com');
const password = ref('Analyst@123');

const roleOptions = [
  { label: '查看', username: 'viewer@example.com', password: 'Viewer@123' },
  { label: '分析', username: 'analyst@example.com', password: 'Analyst@123' },
  { label: '复核', username: 'supervisor@example.com', password: 'Supervisor@123' },
];

function fill(nextUsername: string, nextPassword: string) {
  username.value = nextUsername;
  password.value = nextPassword;
}

async function submit() {
  await auth.login(username.value, password.value);
  const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/';
  await router.replace(redirect);
}
</script>
