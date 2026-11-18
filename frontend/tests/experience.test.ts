import { describe, expect, it, vi } from "vitest";
import { computed } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { dateLabel, setSiteTimezone } from "../src/api";
import { clearFilters, emptyFilter, hasFilters } from "../src/filters";
import { useLibrary } from "../src/store";

describe("gallery experience", () => {
  it("clears effective filters while preserving sort", () => {
    const sorted = { ...emptyFilter(), sort: "oldest" as const, match: "all" as const };
    expect(hasFilters(sorted)).toBe(false);
    expect(hasFilters({ ...sorted, include_no_faces: true })).toBe(true);
    expect(clearFilters({ ...sorted, people: [1] })).toEqual({ ...emptyFilter(), sort: "oldest" });
  });
  it("reactively formats publication times to the minute", () => {
    setSiteTimezone("Asia/Shanghai");
    const label = computed(() => dateLabel("2026-01-01T15:04:59Z"));
    expect(label.value).toContain("23:04");
    setSiteTimezone("UTC");
    expect(label.value).toContain("15:04");
    expect(dateLabel(null)).toBe("缺少日期");
  });
  it("shares concurrent loads and caches site configuration until forced", async () => {
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {} }));
    const fetch = vi.fn(async (url: string) => ({
      ok: true, json: async () => url.endsWith("/site") ? { timezone: "UTC" } : [],
    }));
    vi.stubGlobal("fetch", fetch);
    setActivePinia(createPinia());
    const store = useLibrary();
    await Promise.all([store.loadSite(), store.loadSite(), store.load(), store.load()]);
    expect(fetch).toHaveBeenCalledTimes(3);
    await store.loadSite();
    expect(fetch).toHaveBeenCalledTimes(3);
    await store.loadSite(true);
    expect(fetch).toHaveBeenCalledTimes(4);
    vi.unstubAllGlobals();
  });
});
