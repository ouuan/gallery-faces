<script setup lang="ts">
import { ref, computed, watch } from "vue";
const props = defineProps<{ text?: string | null }>(),
  expanded = ref(false),
  paragraph = ref<HTMLElement | null>(null),
  truncated = ref(false);
watch(() => props.text, () => { expanded.value = false; });
watch([paragraph, expanded, () => props.text], ([element, isExpanded], _, onCleanup) => {
  // Keep the collapse action available while the full text is shown.
  if (!element || isExpanded) return;
  const measure = () => {
    truncated.value = element.scrollHeight > element.clientHeight;
  };
  measure();
  const observer = new ResizeObserver(measure);
  observer.observe(element);
  onCleanup(() => observer.disconnect());
}, { flush: "post" });
const parts = computed(() =>
  (props.text || "")
    .split(/(https?:\/\/[^\s<>]+)/g)
    .map((value) => ({ value, link: /^https?:\/\//.test(value) })),
);
</script>
<template>
  <div v-if="text">
    <p ref="paragraph" class="post-text" :class="{ clamped: !expanded }">
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
    <button v-if="expanded || truncated" class="text-button" :aria-expanded="expanded" @click="expanded = !expanded">
      {{ expanded ? "收起正文" : "展开正文" }}
    </button>
  </div>
  <p v-else class="muted">未获取正文</p>
</template>
