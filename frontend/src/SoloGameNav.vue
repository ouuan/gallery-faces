<script setup lang="ts">
defineProps<{ roomsPath: string; query: Record<string, string> }>();
</script>

<template>
  <nav aria-label="游戏导航">
    <slot />
    <router-link :to="{ path: roomsPath, query }">多人对战</router-link>
    <router-link :to="{ path: '/', query }">返回图库</router-link>
  </nav>
</template>

<style scoped>
nav { display: flex; align-items: center; gap: 12px; }
a { display: inline-flex; align-items: center; justify-content: center; min-height: 44px; white-space: nowrap; }
</style>
