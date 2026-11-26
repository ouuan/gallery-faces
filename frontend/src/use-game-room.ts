import { computed, onScopeDispose, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api, ApiError } from './api';
import type { components } from './schema';

type Schema = components['schemas'];
export type RoomView = Schema['RoomView'];
export type RoomAction = Schema['RoomAction'];
export type Settings = Required<Schema['RoomSettings']>;
const base = '/face-game/rooms';
const key = (code: string) => `face-room:${code}`;

export function useGameRoom() {
  const route = useRoute(), router = useRouter();
  const code = computed(() => String(route.params.code || '').toUpperCase());
  const token = ref(''), room = ref<RoomView | null>(null), busy = ref(false), error = ref(''), syncError = ref('');
  const now = ref(Date.now()), deadline = ref<number | null>(null);
  const seconds = computed(() => deadline.value === null ? null : Math.max(0, Math.ceil((deadline.value - now.value) / 1000)));
  const timer = window.setInterval(() => { now.value = Date.now(); }, 250);
  onScopeDispose(() => clearInterval(timer));
  watch(code, value => {
    token.value = value ? sessionStorage.getItem(key(value)) || '' : '';
    error.value = ''; syncError.value = '';
  }, { immediate: true });

  function apply(view: RoomView) {
    if (view.code !== code.value || (room.value && view.version < room.value.version)) return;
    room.value = view;
    now.value = Date.now();
    deadline.value = view.remaining === null ? null : now.value + view.remaining * 1000;
  }
  watch([code, token], ([current, credential], _, cleanup) => {
    const controller = new AbortController();
    cleanup(() => controller.abort());
    room.value = null; deadline.value = null;
    if (!current || !credential) return;
    async function sync() {
      while (!controller.signal.aborted) {
        try {
          const after = room.value ? `?after=${room.value.version}` : '';
          const view = await api<RoomView>(`${base}/${current}${after}`, { signal: controller.signal, headers: { 'X-Room-Token': credential } });
          if (controller.signal.aborted) return;
          syncError.value = ''; apply(view);
        } catch (cause) {
          if (controller.signal.aborted) return;
          if (cause instanceof ApiError && [403, 404].includes(cause.status)) {
            sessionStorage.removeItem(key(current)); token.value = ''; error.value = cause.message; return;
          }
          syncError.value = '连接中断，正在重新连接…';
          await new Promise(resolve => window.setTimeout(resolve, 1500));
        }
      }
    }
    void sync();
  }, { immediate: true });

  async function enter(nickname: string, target: string, create?: { settings: Settings; filters: Partial<Schema['GameFilters']> }) {
    if (busy.value) return;
    busy.value = true; error.value = '';
    try {
      const existing = target && sessionStorage.getItem(key(target));
      const member = existing ? { code: target, token: existing } : await api<Schema['Membership']>(create ? base : `${base}/${encodeURIComponent(target)}/join`, {
        method: 'POST', body: JSON.stringify({ nickname, ...create }),
      });
      sessionStorage.setItem(key(member.code), member.token);
      if (member.code === code.value) token.value = member.token;
      else await router.push({ path: `${base}/${member.code}`, query: route.query });
    } catch (cause) { error.value = (cause as Error).message; }
    finally { busy.value = false; }
  }
  async function act(action: RoomAction['action'], fields: Partial<RoomAction> = {}) {
    const view = room.value;
    if (!view || busy.value) return;
    busy.value = true; error.value = '';
    try {
      const result = await api<RoomView>(`${base}/${view.code}/actions`, { method: 'POST', headers: { 'X-Room-Token': token.value },
        body: JSON.stringify({ ...fields, action, stage: view.stage }) });
      if (view.code !== code.value) return;
      if (action === 'leave') {
        if (view.phase === 'lobby') sessionStorage.removeItem(key(view.code));
        await router.push({ path: base, query: route.query });
      } else apply(result);
    } catch (cause) { if (view.code === code.value) error.value = (cause as Error).message; }
    finally { busy.value = false; }
  }
  return { code, token, room, busy, error, syncError, seconds, enter, act };
}
