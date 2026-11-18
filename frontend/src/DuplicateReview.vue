<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { NButton, NModal, useMessage } from "naive-ui";
import { Copy } from "@lucide/vue";
import { api, send, platformLabel, dateLabel, type Source } from "./api";
import { useLibrary } from "./store";

type CandidateImage = {
  id: number; width: number; height: number; group_id: number;
  people: { name: string }[]; sources: Source[];
};
type Candidate = { a: number; b: number; decision: string; score: number | null; images: CandidateImage[] };
const props = defineProps<{ rows: Candidate[] }>();
const emit = defineEmits<{ 'update:rows': [rows: Candidate[]] }>();
const store = useLibrary(), message = useMessage();
const current = ref(0), saving = ref(false), details = ref<CandidateImage | null>(null);
const row = computed(() => props.rows[current.value]);
const failedImages = ref(new Set<number>());
const people = (image: CandidateImage) => image.people.map(p => p.name).join("、") || "未知人物";
watch(() => props.rows, (rows, previous) => {
  const selected = previous[current.value];
  const index = rows.findIndex(r => r.a === selected?.a && r.b === selected?.b);
  current.value = index >= 0 ? index : Math.max(0, Math.min(current.value, rows.length - 1));
});
async function decide(action: "merge" | "separate") {
  if (saving.value || !row.value) return;
  saving.value = true;
  const { a, b } = row.value;
  try {
    await send("/admin/duplicates", { a, b, action });
    emit('update:rows', await api<Candidate[]>("/admin/duplicates"));
  } catch (e) {
    message.error((e as Error).message);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div v-if="!row" class="duplicates-empty">
    <Copy :size="40" /><h2>暂无重复图片候选</h2>
    <p>导入图片后自动检测相同文件和尺寸、压缩变体。</p>
  </div>
  <article v-else class="duplicate-review" aria-label="重复图片审核">
    <nav class="duplicate-navigation" aria-label="候选组切换">
      <n-button :disabled="saving || current === 0" @click="current--">上一组</n-button>
      <span aria-live="polite">第 {{ current + 1 }} / {{ rows.length }} 组</span>
      <n-button :disabled="saving || current === rows.length - 1" @click="current++">下一组</n-button>
    </nav>
    <div class="duplicate-heading">
      <h3>#{{ row.a }} 与 #{{ row.b }}</h3>
      <span>{{ row.decision }} · SSIM {{ row.score?.toFixed(3) ?? '—' }}</span>
    </div>
    <div class="duplicate-pair">
      <section v-for="image in row.images" :key="image.id" class="duplicate-photo" :aria-label="`图片 #${image.id}`">
        <div class="duplicate-image">
          <p v-if="failedImages.has(image.id)" role="status">图片加载失败</p>
          <img v-else :src="`/api/v1/admin/media/${image.id}`" :alt="`重复图片候选 #${image.id}`" @error="failedImages.add(image.id)" />
        </div>
        <div class="duplicate-caption">
          <p>{{ image.width }} × {{ image.height }}</p>
          <p class="duplicate-people">{{ people(image) }}</p>
          <n-button :aria-label="`查看图片 #${image.id} 详情`" @click="details = image">查看详情</n-button>
        </div>
      </section>
    </div>
    <div class="duplicate-actions">
      <n-button type="primary" :disabled="saving" :loading="saving" @click="decide('merge')">合并为一组</n-button>
      <n-button :disabled="saving" @click="decide('separate')">{{ row.images[0]?.group_id === row.images[1]?.group_id ? '拆分图片' : '不是重复' }}</n-button>
    </div>
  </article>
  <n-modal :show="!!details" @update:show="!$event && (details = null)" preset="card" role="dialog" aria-modal="true" :title="`图片 #${details?.id} 详情`" class="duplicate-details-dialog" :bordered="false">
    <template v-if="details">
      <p>{{ details.width }} × {{ details.height }}</p>
      <h3>人物</h3><p>{{ people(details) }}</p>
      <h3>来源</h3>
      <p v-if="!details.sources.length" class="muted">暂无来源</p>
      <p v-for="source in details.sources" :key="source.id">
        <a :href="source.url" target="_blank" rel="noopener noreferrer">{{ platformLabel(source.platform) }} · {{ store.publisherName(source) }} · {{ dateLabel(source.published_at) }}</a>
      </p>
      <p class="hint">拆分后的图片不会再次自动合并。</p>
    </template>
  </n-modal>
</template>

<style scoped>
.duplicate-review { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 12px; }
.duplicate-navigation, .duplicate-heading, .duplicate-actions { display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
.duplicate-navigation { justify-content: space-between; font-variant-numeric: tabular-nums; }
.duplicate-heading { justify-content: space-between; font-size: 13px; }
.duplicate-pair { flex: 1; min-height: 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }
.duplicate-photo { min-width: 0; min-height: 0; display: flex; flex-direction: column; gap: 8px; }
.duplicate-image { flex: 1; min-height: 0; min-width: 0; display: flex; align-items: center; justify-content: center; background: var(--panel); }
.duplicate-image img { display: block; width: 100%; height: 100%; object-fit: scale-down; }
.duplicate-caption { flex-shrink: 0; min-width: 0; font-size: 13px; }
.duplicate-people { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.duplicate-caption .n-button { margin-top: 4px; }
.duplicates-empty { flex: 1; min-height: 0; display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 8px; text-align: center; }
@media (max-width: 640px), (max-height: 600px) {
  .duplicate-review { gap: 8px; }
  .duplicate-pair { gap: 12px; }
}
@media (max-height: 600px) {
  .duplicate-caption { display: grid; grid-template-columns: minmax(0, 1fr) auto; column-gap: 8px; }
  .duplicate-caption .n-button { grid-column: 2; grid-row: 1 / 3; margin: 0; }
}
</style>
<style>
.duplicate-details-dialog { width: min(560px, calc(100vw - 32px)); max-height: calc(100dvh - 32px); overflow-y: auto; overflow-wrap: anywhere; }
.duplicate-details-dialog h3 { margin: 16px 0 8px; }
.duplicate-details-dialog p + p { margin-top: 8px; }
</style>
