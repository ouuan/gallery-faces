import { effectScope, nextTick, ref } from "vue";
import { afterEach, expect, it, vi } from "vitest";
import { useImageDownloads, useReviewImages } from "../src/use-review-images";

afterEach(() => vi.unstubAllGlobals());

it("cancels old group downloads, ignores late bodies and releases image URLs on exit", async () => {
  const requests: { signal: AbortSignal; resolve: (response: Response) => void }[] = [];
  const fetch = vi.fn((_url: string, options: RequestInit) => new Promise<Response>(resolve => {
    requests.push({ signal: options.signal!, resolve });
  }));
  const createObjectURL = vi.fn(() => "blob:current");
  const revokeObjectURL = vi.fn();
  vi.stubGlobal("fetch", fetch);
  vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
  const ids = ref([1, 2]);
  const scope = effectScope();
  const images = scope.run(() => useReviewImages(() => ids.value))!;
  let finishBody!: (blob: Blob) => void;
  requests[0].resolve({ ok: true, blob: () => new Promise<Blob>(resolve => { finishBody = resolve; }) } as Response);
  await vi.waitFor(() => expect(finishBody).toBeDefined());

  ids.value = [3, 4];
  await nextTick();
  expect(requests.slice(0, 2).every(request => request.signal.aborted)).toBe(true);
  expect(fetch.mock.calls.map(([url]) => url)).toEqual([1, 2, 3, 4].map(id => `/api/v1/admin/media/${id}`));
  finishBody(new Blob());
  requests[1].resolve({ ok: false } as Response);
  requests[2].resolve({ ok: true, blob: async () => new Blob() } as Response);
  await vi.waitFor(() => expect(images.urls.value.get(3)).toBe("blob:current"));
  expect([...images.urls.value.keys()]).toEqual([3]);
  expect(images.failed.value.size).toBe(0);
  expect(createObjectURL).toHaveBeenCalledTimes(1);

  scope.stop();
  expect(requests.every(request => request.signal.aborted)).toBe(true);
  expect(revokeObjectURL).toHaveBeenCalledWith("blob:current");
});

it("releases previous images and retries failures when revisiting a group", async () => {
  vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:loaded"), revokeObjectURL: vi.fn() });
  const fetch = vi.fn().mockResolvedValueOnce({ ok: false })
    .mockResolvedValue({ ok: true, blob: async () => new Blob() });
  vi.stubGlobal("fetch", fetch);
  const ids = ref([1]);
  const scope = effectScope();
  const images = scope.run(() => useReviewImages(() => ids.value))!;
  await vi.waitFor(() => expect(images.failed.value.has(1)).toBe(true));
  ids.value = [2];
  await vi.waitFor(() => expect(images.urls.value.has(2)).toBe(true));
  expect(images.failed.value.size).toBe(0);
  ids.value = [1];
  await vi.waitFor(() => expect(images.urls.value.has(1)).toBe(true));
  expect(images.urls.value.has(2)).toBe(false);
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:loaded");
  scope.stop();
});

it("preserves pending and loaded sources across metadata refreshes and overlapping groups", async () => {
  const requests: { signal: AbortSignal; resolve: (response: Response) => void }[] = [];
  vi.stubGlobal("fetch", vi.fn((_url: string, options: RequestInit) => new Promise<Response>(resolve => {
    requests.push({ signal: options.signal!, resolve });
  })));
  vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:retained"), revokeObjectURL: vi.fn() });
  const ids = ref([1]);
  const scope = effectScope();
  const images = scope.run(() => useReviewImages(() => ids.value))!;
  ids.value = [1];
  await nextTick();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(requests[0].signal.aborted).toBe(false);
  requests[0].resolve({ ok: true, blob: async () => new Blob() } as Response);
  await vi.waitFor(() => expect(images.urls.value.get(1)).toBe("blob:retained"));
  ids.value = [1, 2];
  await nextTick();
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(images.urls.value.get(1)).toBe("blob:retained");
  expect(URL.revokeObjectURL).not.toHaveBeenCalled();
  ids.value = [2];
  await nextTick();
  expect(requests[0].signal.aborted).toBe(true);
  expect(requests[1].signal.aborted).toBe(false);
  expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
  scope.stop();
});


it("reloads a changed URL for the same ID and retries a failed source on refresh", async () => {
  vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:loaded"), revokeObjectURL: vi.fn() });
  const fetch = vi.fn().mockResolvedValueOnce({ ok: true, blob: async () => new Blob() })
    .mockResolvedValueOnce({ ok: false })
    .mockResolvedValue({ ok: true, blob: async () => new Blob() });
  vi.stubGlobal("fetch", fetch);
  const sources = ref([{ id: 0, url: "/first.jpg" }]);
  const scope = effectScope();
  const images = scope.run(() => useImageDownloads(() => sources.value))!;
  await vi.waitFor(() => expect(images.urls.value.has(0)).toBe(true));
  sources.value = [{ id: 0, url: "/replacement.jpg" }];
  await vi.waitFor(() => expect(images.failed.value.has(0)).toBe(true));
  expect(images.urls.value.has(0)).toBe(false);
  expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
  sources.value = [...sources.value];
  await vi.waitFor(() => expect(images.urls.value.has(0)).toBe(true));
  expect(images.failed.value.size).toBe(0);
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(["/first.jpg", "/replacement.jpg", "/replacement.jpg"]);
  scope.stop();
});
