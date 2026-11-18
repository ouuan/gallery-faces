import { onMounted, onUnmounted, watch, type Ref } from "vue";

/** Position cards without changing their DOM (and keyboard navigation) order. */
export function useMasonry(
  container: Ref<HTMLElement | null>,
  enabled: () => boolean,
  items: () => unknown,
) {
  let observer: ResizeObserver | undefined;
  let frame = 0;
  let observedWidth = -1;
  let observedContainer: HTMLElement | null = null;
  let cards: HTMLElement[] = [];

  function arrange() {
    frame = 0;
    const grid = container.value;
    if (!grid || !enabled()) return;
    const style = getComputedStyle(grid);
    const columns = Number(style.getPropertyValue("--masonry-columns"));
    const gap = parseFloat(style.columnGap);
    const width = grid.getBoundingClientRect().width;
    if (!width || !columns) return;
    const cardWidth = (width - gap * (columns - 1)) / columns;
    const bottoms = Array<number>(columns).fill(0);
    // Read every height before writing positions to avoid repeated layout work.
    const heights = cards.map((card) => card.getBoundingClientRect().height);
    cards.forEach((card, index) => {
      const top = Math.min(...bottoms);
      const column = bottoms.indexOf(top);
      card.style.setProperty("--masonry-left", `${column * (cardWidth + gap)}px`);
      card.style.setProperty("--masonry-top", `${top}px`);
      // The caption's existing bottom padding supplies the vertical spacing.
      bottoms[column] = top + heights[index];
    });
    grid.style.height = `${Math.max(...bottoms)}px`;
  }

  function schedule() {
    if (!frame) frame = requestAnimationFrame(arrange);
  }

  function reset() {
    observer?.disconnect();
    cancelAnimationFrame(frame);
    frame = 0;
    observedContainer?.style.removeProperty("height");
    for (const card of cards) {
      card.style.removeProperty("--masonry-left");
      card.style.removeProperty("--masonry-top");
    }
    cards = [];
  }

  function refresh() {
    reset();
    observedContainer = container.value;
    observedWidth = -1;
    if (!observedContainer || !enabled()) return;
    cards = Array.from(observedContainer.children) as HTMLElement[];
    observer?.observe(observedContainer);
    cards.forEach((card) => observer?.observe(card));
    arrange();
  }

  watch([container, enabled, items], refresh, { flush: "post" });
  onMounted(() => {
    observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.target !== observedContainer) {
          schedule();
        } else if (entry.contentRect.width !== observedWidth) {
          observedWidth = entry.contentRect.width;
          schedule();
        }
      }
    });
    window.addEventListener("resize", schedule);
    refresh();
  });
  onUnmounted(() => {
    reset();
    window.removeEventListener("resize", schedule);
  });
}
