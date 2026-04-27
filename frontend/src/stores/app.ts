import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { getDailyRiskReport, getOverview, getSampleQuestions, getSchema } from '@/api/client';
import type { DailyRiskReport, OverviewResponse, SampleQuestion, SchemaCatalog } from '@/types/api';

export const useAppStore = defineStore('app', () => {
  const overview = ref<OverviewResponse | null>(null);
  const schema = ref<SchemaCatalog | null>(null);
  const dailyRisk = ref<DailyRiskReport | null>(null);
  const sampleQuestions = ref<SampleQuestion[]>([]);
  const loading = ref(false);
  const error = ref('');

  const isReady = computed(() => Boolean(overview.value && schema.value && dailyRisk.value));

  async function loadDashboard() {
    loading.value = true;
    error.value = '';
    try {
      const [overviewPayload, schemaPayload, dailyPayload, samples] = await Promise.all([
        getOverview(),
        getSchema(),
        getDailyRiskReport(),
        getSampleQuestions(),
      ]);
      overview.value = overviewPayload;
      schema.value = schemaPayload;
      dailyRisk.value = dailyPayload;
      sampleQuestions.value = samples;
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
    } finally {
      loading.value = false;
    }
  }

  return {
    overview,
    schema,
    dailyRisk,
    sampleQuestions,
    loading,
    error,
    isReady,
    loadDashboard,
  };
});
