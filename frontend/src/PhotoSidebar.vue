<script setup lang="ts">
import type { Photo } from './api';
import PhotoSources from './PhotoSources.vue';
import FeedbackPanel from './FeedbackPanel.vue';

const props = defineProps<{ detail: Photo; authenticated: boolean; query: Record<string, string>; inlinePost?: boolean; feedbackFirst?: boolean; defaultFace?: number; defaultPerson?: number | null; draftKey?: string; submitted?: (faceId: number | null) => void }>();
const emit = defineEmits<{ changed: [] }>();
</script>
<template>
  <aside class="detail-sidebar">
    <template v-for="section in feedbackFirst ? ['feedback', 'summary', 'sources'] : ['summary', 'sources', 'feedback']" :key="section">
    <FeedbackPanel v-if="section === 'feedback'" :key="detail.image_id" :image-id="detail.image_id" :photo="detail" :default-face="defaultFace" :default-person="defaultPerson" :draft-key="draftKey" :submitted="submitted"
      :pending-count="detail.pending_feedback_count" @changed="emit('changed')" />
    <header v-else-if="section === 'summary'" class="detail-summary">
      <h2>{{ detail.people.map((p) => p.name).join("、") || "未知人物" }}</h2>
      <div v-if="authenticated" class="detail-manage-actions">
        <router-link class="detail-manage" :to="{ path: '/admin/review', query: { state: 'image', image: detail.image_id } }">管理此图片</router-link>
        <router-link class="detail-manage" :to="{ path: '/admin/duplicates', query: { image: detail.image_id } }">审核重复图片</router-link>
      </div>
    </header>
    <PhotoSources v-else :detail="detail" :query="query" :inline-post="inlinePost" />
    </template>
  </aside>
</template>
<style scoped>
.detail-sidebar > :deep(.feedback-panel:first-child) { margin: 0 0 24px; }
</style>
