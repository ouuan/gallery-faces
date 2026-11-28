<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { NButton } from 'naive-ui';
import { api, type Photo } from './api';
import PhotoSources from './PhotoSources.vue';
import PhotoSidebar from './PhotoSidebar.vue';
import { useLatestRequest } from './use-latest-request';

const props = defineProps<{ groupId: number; imageId: number; query: Record<string, string>; solo?: boolean; wrong?: boolean; faceId?: number; choice?: number | null; draftKey?: string; submitted?: (faceId: number | null, feedbackId: number) => void }>();
const authenticated = ref(false);
const detail = ref<Photo | null>(null), error = ref(''), request = useLatestRequest();
async function load() {
  const signal = request.start();
  error.value = '';
  try {
    const result = await api<Photo>(`/gallery/${props.groupId}`, { signal });
    if (result.image_id !== props.imageId) throw new Error('这张照片的代表图已更换');
    if (!signal.aborted) detail.value = result;
  } catch (cause) { if (!signal.aborted) error.value = (cause as Error).message; }
}
onMounted(load);
onMounted(() => { if (props.solo) api('/session').then(session => { authenticated.value = session.admin; }).catch(() => {}); });
</script>
<template>
  <div class="room-sources">
    <PhotoSidebar v-if="detail && solo" :detail="detail" :authenticated="authenticated" inline-post :query="query" :feedback-first="wrong" :default-face="wrong ? faceId : undefined" :default-person="wrong ? choice : null" :draft-key="draftKey" :submitted="submitted" @changed="detail.pending_feedback_count = (detail.pending_feedback_count ?? 0) + 1" />
    <PhotoSources v-else-if="detail" :detail="detail" :query="query" new-tab />
    <p v-else-if="error" role="alert">{{ error }} <n-button @click="load">重试加载来源</n-button></p>
    <p v-else role="status">正在加载来源…</p>
  </div>
</template>
<style scoped>
.room-sources { border-top: 1px solid var(--line); margin-top: 18px; padding-top: 14px; }
</style>
