<script lang="ts">
const scripts = new Map<string, Promise<void>>();
function script(src: string) {
  if (!scripts.has(src)) {
    const promise = new Promise<void>((resolve, reject) => {
      const el = document.createElement('script'); el.src = src; el.async = true;
      const timer = setTimeout(() => { el.remove(); reject(new Error('timeout')); }, 15000);
      el.onload = () => { clearTimeout(timer); resolve(); };
      el.onerror = () => { clearTimeout(timer); el.remove(); reject(new Error('script')); };
      document.head.append(el);
    }).catch(e => { scripts.delete(src); throw e; });
    scripts.set(src, promise);
  }
  return scripts.get(src)!;
}
export type Post = { id: number; key: string; platform: string; url: string; embed_id: string | null; author: string; author_name: string | null; published_at: string };
</script>
<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch, computed } from 'vue';
import { NButton } from 'naive-ui';
import { useLibrary } from './store';
const props = defineProps<{ post: Post }>();
const store = useLibrary();
const host = ref<HTMLElement>(); const failed = ref(false); const busy = ref(false);
let observer: IntersectionObserver | undefined; let generation = 0; let active = false;
const url = computed(() => {
  try { const u = new URL(props.post.url); return u.protocol === 'https:' && !u.username && !u.password && !u.port && /^(www\.)?(x\.com|twitter\.com|instagram\.com)$/.test(u.hostname) ? u.href : null; } catch { return null; }
});
async function render() {
  const version = ++generation; failed.value = false; busy.value = true;
  const box = document.createElement('div'); host.value?.replaceChildren(box);
  try {
    if (!url.value || !props.post.embed_id) throw new Error('url');
    const work = async () => {
      if (props.post.platform === 'x') {
        await script('https://platform.twitter.com/widgets.js');
        if (version !== generation) return;
        const el = await (window as any).twttr.widgets.createTweet(props.post.embed_id, box, { lang: 'ja', theme: store.dark ? 'dark' : 'light', conversation: 'none', dnt: true });
        if (!el) throw new Error('unavailable');
      } else {
        const block = document.createElement('blockquote'); block.className = 'instagram-media';
        block.dataset.instgrmPermalink = `https://www.instagram.com/p/${props.post.embed_id}/`; block.dataset.instgrmVersion = '14';
        box.append(block);
        await script('https://www.instagram.com/embed.js');
        if (version !== generation) return;
        (window as any).instgrm.Embeds.process();
        await new Promise<void>((resolve, reject) => {
          const start = Date.now();
          const poll = () => {
            if (version !== generation) return resolve();
            if (box.querySelector('iframe')) return resolve();
            if (Date.now() - start > 12000) return reject(new Error('timeout'));
            setTimeout(poll, 200);
          }; poll();
        });
      }
    };
    let timer: ReturnType<typeof setTimeout> | undefined;
    try { await Promise.race([work(), new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('timeout')), 20000); })]); }
    finally { clearTimeout(timer); }
  } catch { if (version === generation) { failed.value = true; host.value?.replaceChildren(); generation++; } }
  finally { if (version === generation || failed.value) busy.value = false; }
}
onMounted(() => { observer = new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting)) { active = true; observer?.disconnect(); void render(); } }, { rootMargin: '400px' }); if (host.value) observer.observe(host.value); });
watch(() => store.dark, () => { if (active && props.post.platform === 'x') void render(); });
onBeforeUnmount(() => { generation++; observer?.disconnect(); });
</script>
<template>
  <article class="post-embed">
    <div v-show="!failed" ref="host" class="embed-host" />
    <p v-if="busy" class="embed-status muted" role="status">投稿を読み込み中…</p>
    <p v-if="failed" class="embed-status" role="status">投稿を表示できません。<n-button text @click="render">再試行</n-button></p>
    <a v-if="url" class="post-source" :href="url" target="_blank" rel="noopener noreferrer">{{ post.platform === 'x' ? 'X' : 'Instagram' }}で投稿を見る</a>
  </article>
</template>
<style scoped>
.post-embed { display: grid; gap: 8px; min-width: 0; border-bottom: 1px solid var(--line); padding-bottom: 16px; overflow-wrap: anywhere; }
.embed-host { min-width: 0; min-height: 100px; }
/* Both platforms fill the same responsive column, including their inline-sized wrappers. */
.embed-host :deep(iframe), .embed-host :deep(blockquote), .embed-host :deep(.twitter-tweet) {
  width: 100% !important;
  min-width: 0 !important;
  max-width: 100% !important;
}
.embed-host :deep(.twitter-tweet), .embed-host :deep(.instagram-media) { margin: 0 auto !important; }
.embed-status { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.post-source { display: inline-flex; align-items: center; justify-self: start; min-height: 44px; }
</style>
