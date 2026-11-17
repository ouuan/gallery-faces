<script setup lang="ts">
import { ref, computed } from "vue";
const props = defineProps<{ text?: string | null }>(),
  expanded = ref(false);
const parts = computed(() =>
  (props.text || "")
    .split(/(https?:\/\/[^\s<>]+)/g)
    .map((value) => ({ value, link: /^https?:\/\//.test(value) })),
);
</script>
<template>
  <div v-if="text">
    <p class="post-text" :class="{ clamped: !expanded }">
      <template v-for="(part, i) in parts" :key="i"
        ><a
          v-if="part.link"
          :href="part.value"
          target="_blank"
          rel="noopener noreferrer"
          >{{ part.value }}</a
        ><template v-else>{{ part.value }}</template></template
      >
    </p>
    <button class="text-button" @click="expanded = !expanded">
      {{ expanded ? "收起正文" : "展开正文" }}
    </button>
  </div>
  <p v-else class="muted">未获取正文</p>
</template>
