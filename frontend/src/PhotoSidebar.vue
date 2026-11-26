<script setup lang="ts">
import { ExternalLink } from '@lucide/vue';
import { dateLabel, platformLabel, type Photo } from './api';
import { useLibrary } from './store';
import { t } from './locale';
import SourceText from './SourceText.vue';
import FeedbackPanel from './FeedbackPanel.vue';

const props = defineProps<{ detail: Photo; authenticated: boolean; query: Record<string, string>; inlinePost?: boolean; feedbackFirst?: boolean; defaultFace?: number; defaultPerson?: number | null; draftKey?: string; submitted?: (faceId: number | null) => void }>();
const emit = defineEmits<{ changed: [] }>();
const store = useLibrary();
function postLink(key: string) {
  const state = { fromPhoto: true };
  return props.inlinePost ? { query: { ...props.query, post: key }, state }
    : { name: 'gallery-post', params: { key }, query: props.query, state };
}
function coauthorLabel(coauthor: { username: string; full_name?: string | null }) {
  const name = coauthor.full_name?.trim();
  const username = coauthor.username?.trim();
  return name && username ? `${name} (@${username})` : name || (username ? `@${username}` : "");
}
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
    <section v-else class="detail-sources" aria-label="图片来源">
      <h2 class="detail-sources-heading">来源 · {{ detail.source_count }}</h2>
      <div v-for="source in detail.sources" :key="source.id" class="source-block">
        <header class="source-header">
          <h3>
            <router-link class="source-title-link" :to="postLink(source.key ?? `${source.platform}:record:${source.id}`)">
              <span>{{ platformLabel(source.platform) }} · {{ store.publisherName(source) }}</span>
            </router-link><a class="icon-link" :href="source.url" target="_blank" rel="noopener noreferrer" title="打开原帖" aria-label="打开原帖"><ExternalLink :size="16" aria-hidden="true" /></a>
          </h3>
          <div class="source-meta">
            <time :datetime="source.published_at">{{ dateLabel(source.published_at) }}</time>
            <span v-if="source.images?.length" class="source-resolution">
              <span aria-hidden="true">·</span>
              <span>{{ [...new Set(source.images.map(image => image.width + " × " + image.height))].join("、") }}</span>
            </span>
          </div>
          <div v-if="source.coauthors?.length" class="source-coauthors">
            <strong>{{ t("共同作者") }}</strong>
            <span>{{ source.coauthors.map(coauthorLabel).filter(Boolean).join("、") }}</span>
          </div>
        </header>
        <SourceText :text="source.post_text" />
      </div>
    </section>
    </template>
  </aside>
</template>
<style scoped>
.detail-sidebar > :deep(.feedback-panel:first-child) { margin: 0 0 24px; }
</style>
