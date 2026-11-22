<script setup lang="ts">
import { ref, watch } from 'vue';

const props = defineProps<{ src: string; fallback?: string; alt: string; width: number; height: number; boxes: { box: number[]; label: string; active?: boolean }[] }>();
const source = ref(props.src);
const failed = ref(false);
watch(() => props.src, value => { source.value = value; failed.value = false; });
function unavailable() {
  if (props.fallback && source.value !== props.fallback) source.value = props.fallback;
  else failed.value = true;
}
</script>

<template>
  <div class="evidence-stage">
    <span v-if="failed" class="muted">{{ alt }}不可用</span>
    <div v-else class="evidence-frame" :style="{ '--ratio': width / height, aspectRatio: `${width} / ${height}` }">
      <img :src="source" :alt="alt" loading="lazy" @error="unavailable" />
      <span v-for="({box, label, active}, index) in boxes" :key="index" aria-hidden="true" class="face-outline" :class="{ active }"
        :style="{ left: `${box[0] / width * 100}%`, top: `${box[1] / height * 100}%`, width: `${box[2] / width * 100}%`, height: `${box[3] / height * 100}%` }">
        <b>{{ label }}</b>
      </span>
    </div>
  </div>
</template>

<style scoped>
.evidence-stage { display: grid; place-items: center; background: var(--panel); border: 1px solid var(--line); border-radius: 6px; overflow: hidden; min-height: 44px; }
.evidence-frame { width: min(100%, calc(50dvh * var(--ratio))); position: relative; }
.evidence-frame img { display: block; width: 100%; height: 100%; object-fit: contain; }
.face-outline { position: absolute; border: 2px solid white; outline: 1px solid #20242b; color: #20242b; }
.face-outline b { display: block; width: max-content; padding: 0 4px; background: white; font-size: 12px; line-height: 16px; }
.face-outline.active { border-color: var(--accent); }
.face-outline.active b { background: var(--selection); color: var(--accent); }
</style>
