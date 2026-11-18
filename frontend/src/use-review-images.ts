import { ref, watch } from "vue";

export function useReviewImages(imageIds: () => number[]) {
  return useImageDownloads(() => [...new Set(imageIds())].map(id => ({ id, url: `/api/v1/admin/media/${id}` })));
}

export function useImageDownloads(sources: () => { id: number; url: string }[]) {
  const urls = ref(new Map<number, string>());
  const failed = ref(new Set<number>());

  watch(sources, (images, _, onCleanup) => {
    const controller = new AbortController();
    const objectUrls = new Map<number, string>();
    urls.value = new Map();
    failed.value = new Set();
    onCleanup(() => {
      controller.abort();
      objectUrls.forEach(url => URL.revokeObjectURL(url));
    });

    for (const { id, url: source } of images) {
      void (async () => {
        try {
          const response = await fetch(source, { signal: controller.signal });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const blob = await response.blob();
          // A completed response can still race with navigation or unmounting.
          if (controller.signal.aborted) return;
          const url = URL.createObjectURL(blob);
          objectUrls.set(id, url);
          urls.value.set(id, url);
        } catch {
          if (!controller.signal.aborted) failed.value.add(id);
        }
      })();
    }
  }, { immediate: true });

  return { urls, failed };
}
