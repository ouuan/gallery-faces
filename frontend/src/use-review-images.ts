import { onScopeDispose, ref, watch } from "vue";

export function useReviewImages(imageIds: () => number[]) {
  return useImageDownloads(() => [...new Set(imageIds())].map(id => ({ id, url: `/api/v1/admin/media/${id}` })));
}

export function useImageDownloads(sources: () => { id: number; url: string }[]) {
  const urls = ref(new Map<number, string>());
  const failed = ref(new Set<number>());
  const downloads = new Map<number, { source: string; controller: AbortController }>();

  function release(id: number) {
    downloads.get(id)?.controller.abort();
    downloads.delete(id);
    const url = urls.value.get(id);
    if (url) URL.revokeObjectURL(url);
    urls.value.delete(id);
    failed.value.delete(id);
  }

  watch(sources, images => {
    const requested = new Map(images.map(({ id, url }) => [id, url]));
    // Metadata updates must not restart unchanged downloads or blank the preview.
    // Keep only current sources, so navigating still promptly releases large blobs.
    for (const [id, download] of downloads) {
      if (requested.get(id) !== download.source || failed.value.has(id)) release(id);
    }
    for (const [id, source] of requested) {
      if (downloads.has(id)) continue;
      const controller = new AbortController();
      downloads.set(id, { source, controller });
      void (async () => {
        try {
          const response = await fetch(source, { signal: controller.signal });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const blob = await response.blob();
          // A completed response can still race with navigation or unmounting.
          if (controller.signal.aborted) return;
          urls.value.set(id, URL.createObjectURL(blob));
        } catch {
          if (!controller.signal.aborted) failed.value.add(id);
        }
      })();
    }
  }, { immediate: true });

  onScopeDispose(() => {
    for (const id of downloads.keys()) release(id);
  });

  return { urls, failed };
}
