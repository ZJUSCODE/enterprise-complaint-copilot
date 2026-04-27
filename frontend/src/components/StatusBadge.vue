<template>
  <span class="status-badge" :class="tone">
    <span class="status-dot" />
    {{ label }}
  </span>
</template>

<script setup lang="ts">
defineProps<{
  label: string;
  tone?: 'ok' | 'warn' | 'danger' | 'neutral';
}>();
</script>
