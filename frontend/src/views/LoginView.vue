<template>
  <div class="login-page">
    <section class="login-panel">
      <div class="login-copy">
        <p class="eyebrow">进入工作台</p>
        <h1>选择身份后继续处理客诉。</h1>
        <p>不同角色对应不同的数据与操作权限。运营分析使用 analyst，人工复核使用 supervisor。</p>
        <RouterLink class="text-link" to="/public">了解平台能力</RouterLink>
      </div>

      <el-alert v-if="auth.error" :title="auth.error" type="error" show-icon />

      <div class="role-options">
        <button
          v-for="item in roleOptions"
          :key="item.username"
          type="button"
          :class="{ active: username === item.username }"
          @click="fill(item.username, item.password)"
        >
          <strong>{{ item.role }}</strong>
          <span>{{ item.intent }}</span>
        </button>
      </div>

      <el-form class="login-form" @submit.prevent="submit">
        <el-form-item label="账号">
          <el-input v-model="username" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="password" type="password" autocomplete="current-password" show-password />
        </el-form-item>
        <el-button type="primary" native-type="submit" :loading="auth.loading">登录</el-button>
      </el-form>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { RouterLink, useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';

const auth = useAuthStore();
const router = useRouter();
const route = useRoute();

const username = ref('analyst@example.com');
const password = ref('Analyst@123');

const roleOptions = [
  { role: 'viewer', intent: '只看风险和结论', username: 'viewer@example.com', password: 'Viewer@123' },
  { role: 'analyst', intent: '查询明细和生成判断', username: 'analyst@example.com', password: 'Analyst@123' },
  { role: 'supervisor', intent: '处理人工复核', username: 'supervisor@example.com', password: 'Supervisor@123' },
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
