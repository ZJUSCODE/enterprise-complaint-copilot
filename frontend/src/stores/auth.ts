import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { getMe, login as loginApi } from '@/api/client';
import type { AuthUser } from '@/types/api';

const TOKEN_KEY = 'copilot_access_token';
const EXPIRES_KEY = 'copilot_token_expires_at';
const USER_KEY = 'copilot_user';

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem(TOKEN_KEY) || '');
  const expiresAt = ref(localStorage.getItem(EXPIRES_KEY) || '');
  const user = ref<AuthUser | null>(JSON.parse(localStorage.getItem(USER_KEY) || 'null') as AuthUser | null);
  const loading = ref(false);
  const error = ref('');

  const isAuthenticated = computed(() => Boolean(token.value && user.value));
  const role = computed(() => user.value?.role || 'viewer');

  function persist(nextToken: string, nextExpiresAt: string, nextUser: AuthUser) {
    token.value = nextToken;
    expiresAt.value = nextExpiresAt;
    user.value = nextUser;
    localStorage.setItem(TOKEN_KEY, nextToken);
    localStorage.setItem(EXPIRES_KEY, nextExpiresAt);
    localStorage.setItem(USER_KEY, JSON.stringify(nextUser));
  }

  function logout() {
    token.value = '';
    expiresAt.value = '';
    user.value = null;
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(EXPIRES_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem('copilot_session_id');
  }

  async function login(username: string, password: string) {
    loading.value = true;
    error.value = '';
    try {
      const payload = await loginApi(username, password);
      persist(payload.access_token, payload.expires_at, payload.user);
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
      logout();
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function refreshMe() {
    if (!token.value) return;
    try {
      const payload = await getMe();
      user.value = payload.user;
      localStorage.setItem(USER_KEY, JSON.stringify(payload.user));
    } catch {
      logout();
    }
  }

  return {
    token,
    expiresAt,
    user,
    loading,
    error,
    isAuthenticated,
    role,
    login,
    logout,
    refreshMe,
  };
});
