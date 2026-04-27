import { defineStore } from 'pinia';
import { ref } from 'vue';
import { getAuditRecent } from '@/api/client';
import { useAuthStore } from '@/stores/auth';
import type { AuditEvent } from '@/types/api';

export const useAuditStore = defineStore('audit', () => {
  const auth = useAuthStore();
  const items = ref<AuditEvent[]>([]);
  const loading = ref(false);
  const error = ref('');

  async function load(limit = 50) {
    loading.value = true;
    error.value = '';
    try {
      const payload = await getAuditRecent(limit, auth.role);
      if (payload.error) {
        throw new Error(payload.error.message);
      }
      items.value = payload.items || [];
    } catch (err) {
      items.value = [];
      error.value = err instanceof Error ? err.message : String(err);
    } finally {
      loading.value = false;
    }
  }

  return {
    items,
    loading,
    error,
    load,
  };
});
