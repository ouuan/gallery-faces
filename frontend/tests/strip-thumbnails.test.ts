import { effectScope, nextTick, ref } from 'vue';
import { afterEach, expect, it, vi } from 'vitest';
import { useStripThumbnails } from '../src/use-strip-thumbnails';

afterEach(() => vi.unstubAllGlobals());

function setup() {
  const callbacks: IntersectionObserverCallback[] = [];
  const disconnect = vi.fn();
  vi.stubGlobal('IntersectionObserver', class {
    constructor(callback: IntersectionObserverCallback) { callbacks.push(callback); }
    observe() {}
    disconnect = disconnect;
  });
  const requests: { signal: AbortSignal; resolve: (response: Response) => void }[] = [];
  vi.stubGlobal('fetch', vi.fn((_url, options) => new Promise<Response>(resolve => {
    requests.push({ signal: options.signal, resolve });
  })));
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:thumbnail'), revokeObjectURL: vi.fn() });
  const element = document.createElement('div');
  element.innerHTML = '<img data-thumbnail="/image/1">';
  const image = element.querySelector('img')!;
  const root = ref<HTMLElement>(element), ids = ref([1]);
  const scope = effectScope();
  scope.run(() => useStripThumbnails(root, () => ids.value));
  function visibility(visible: boolean) {
    callbacks.at(-1)!([{ target: image, isIntersecting: visible } as IntersectionObserverEntry], {} as IntersectionObserver);
  }
  const finish = (index: number) => requests[index].resolve({ ok: true, blob: async () => new Blob() } as Response);
  return { scope, root, ids, image, requests, visibility, finish, disconnect };
}

it('cancels departing downloads, ignores late bodies, retries on return and retains completed thumbnails', async () => {
  const s = setup();
  s.visibility(true);
  let finishBody!: (blob: Blob) => void;
  s.requests[0].resolve({ ok: true, blob: () => new Promise<Blob>(resolve => { finishBody = resolve; }) } as Response);
  await vi.waitFor(() => expect(finishBody).toBeDefined());
  s.visibility(false);
  expect(s.requests[0].signal.aborted).toBe(true);
  s.visibility(true);
  finishBody(new Blob());
  await nextTick();
  expect(URL.createObjectURL).not.toHaveBeenCalled();
  s.finish(1);
  await vi.waitFor(() => expect(s.image.src).toBe('blob:thumbnail'));
  s.visibility(false);
  s.visibility(true);
  s.ids.value = [1];
  await nextTick();
  s.visibility(true);
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(URL.revokeObjectURL).not.toHaveBeenCalled();
  s.scope.stop();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:thumbnail');
  expect(s.image.hasAttribute('src')).toBe(false);
  expect(s.disconnect).toHaveBeenCalled();
});

it('preserves pending requests on refresh and releases changed representatives and removed entries', async () => {
  const s = setup();
  s.visibility(true);
  s.ids.value = [1];
  await nextTick();
  s.visibility(true);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(s.requests[0].signal.aborted).toBe(false);
  s.image.dataset.thumbnail = '/image/2';
  s.ids.value = [2];
  await nextTick();
  expect(s.requests[0].signal.aborted).toBe(true);
  s.visibility(true);
  s.finish(1);
  await vi.waitFor(() => expect(s.image.src).toBe('blob:thumbnail'));
  s.image.remove();
  s.ids.value = [];
  await nextTick();
  expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
  s.scope.stop();
});

it('retries failures on re-entry and aborts pending work on disposal', async () => {
  const s = setup();
  s.visibility(true);
  s.requests[0].resolve({ ok: false } as Response);
  await vi.waitFor(() => expect(s.image.hasAttribute('src')).toBe(false));
  await nextTick();
  s.visibility(false);
  s.visibility(true);
  expect(fetch).toHaveBeenCalledTimes(2);
  s.scope.stop();
  expect(s.requests[1].signal.aborted).toBe(true);
});
