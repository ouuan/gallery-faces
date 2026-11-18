import { onScopeDispose, watch, type Ref } from "vue";

type Thumbnail = {
  source: string;
  controller?: AbortController;
  url?: string;
};

// One observer bounds downloads to the strip plus one thumbnail of headroom.
// Completed blobs live only as long as their queue entries do.
export function useStripThumbnails(root: Ref<HTMLElement | undefined>, imageIds: () => number[]) {
  const downloads = new Map<HTMLImageElement, Thumbnail>();
  function cancel(download: Thumbnail) {
    download.controller?.abort();
    download.controller = undefined;
  }
  function release(image: HTMLImageElement, download: Thumbnail) {
    cancel(download);
    if (download.url) URL.revokeObjectURL(download.url);
    image.removeAttribute("src");
    downloads.delete(image);
  }
  async function load(image: HTMLImageElement, download: Thumbnail) {
    if (download.url || download.controller) return;
    const controller = new AbortController();
    download.controller = controller;
    try {
      const response = await fetch(download.source, { signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      // A cancelled body can finish after re-entry or a representative change.
      if (controller.signal.aborted) return;
      download.url = URL.createObjectURL(blob);
      image.src = download.url;
    } catch {
      // Re-entry or a metadata refresh retries failed and cancelled downloads.
    } finally {
      if (download.controller === controller) download.controller = undefined;
    }
  }
  watch([root, imageIds], ([element], _, onCleanup) => {
    const images = new Set(Array.from(element?.querySelectorAll<HTMLImageElement>("img[data-thumbnail]") ?? []));
    for (const [image, download] of downloads) {
      if (!images.has(image) || image.dataset.thumbnail !== download.source) release(image, download);
    }
    if (!element) return;
    const observer = typeof IntersectionObserver === "undefined" ? null : new IntersectionObserver(entries => {
      // Cancel departures before starting arrivals, regardless of entry order.
      for (const entry of entries) {
        const download = downloads.get(entry.target as HTMLImageElement);
        if (download && !entry.isIntersecting) cancel(download);
      }
      for (const entry of entries) {
        const image = entry.target as HTMLImageElement;
        const download = downloads.get(image);
        if (download && entry.isIntersecting) void load(image, download);
      }
    }, { root: element, rootMargin: "0px 124px" });
    for (const image of images) {
      const source = image.dataset.thumbnail;
      if (!source) continue;
      let download = downloads.get(image);
      if (!download) {
        download = { source };
        downloads.set(image, download);
      }
      if (observer) observer.observe(image);
      else void load(image, download);
    }
    onCleanup(() => observer?.disconnect());
  }, { flush: "post", immediate: true });
  onScopeDispose(() => {
    for (const [image, download] of downloads) release(image, download);
  });
}
