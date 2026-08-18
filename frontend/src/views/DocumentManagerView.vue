<template>
  <div class="document-manager-view">
    <DocumentManager />
  </div>
</template>

<script setup lang="ts">
import DocumentManager from '@/components/DocumentManager.vue';
</script>

<style scoped>
.document-manager-view {
  min-height: 100vh;
  background: var(--bg-page, #f5f7fa);
}
</style>
