<script setup lang="ts">
import { ExternalLink } from '@lucide/vue';
import { dateLabel, platformLabel, type Photo } from './api';
import { useLibrary } from './store';
import { t } from './locale';
import SourceText from './SourceText.vue';

const props = defineProps<{ detail: Photo; query: Record<string, string>; inlinePost?: boolean; newTab?: boolean }>();
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
    <section class="detail-sources" aria-label="图片来源">
      <h2 class="detail-sources-heading">来源 · {{ detail.source_count }}</h2>
      <div v-for="source in detail.sources" :key="source.id" class="source-block">
        <header class="source-header">
          <h3>
            <router-link class="source-title-link" :target="newTab ? '_blank' : undefined" :rel="newTab ? 'noopener noreferrer' : undefined" :to="postLink(source.key ?? `${source.platform}:record:${source.id}`)">
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
