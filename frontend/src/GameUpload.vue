<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { NButton, NInput, useMessage } from 'naive-ui';
import { api } from './api';
import type { RoomView } from './use-game-room';
import type { components } from './schema';
import GameBoardRecords from './GameBoardRecords.vue';

const props = defineProps<{ room: RoomView; token: string; gamePath: string }>();
const player = computed(() => props.room.players.find(member => member.id === props.room.me)!);
const nickname = defineModel<string>('nickname', { required: true });
const submissionKey = `game:score:${props.room.match_id}:${props.room.me}`;
const submittedName = ref(sessionStorage.getItem(submissionKey) || ''), busy = ref(false), message = useMessage();
const board = ref<components['schemas']['BoardView']>(), error = ref(''), retry = ref(0);
watch([submittedName, retry], async (_, __, cleanup) => {
  if (!submittedName.value) return;
  const controller = new AbortController(); cleanup(() => controller.abort());
  error.value = '';
  try {
    board.value = await api(`${props.gamePath}/boards/current`, { method: 'POST', signal: controller.signal,
      body: JSON.stringify({ settings: props.room.settings, filters: props.room.filters }) });
  } catch (cause) { if (!controller.signal.aborted) error.value = (cause as Error).message; }
}, { immediate: true });
async function upload() {
  if (busy.value || submittedName.value) return;
  busy.value = true;
  try {
    const result = await api<components['schemas']['Record']>(`${props.gamePath}/matches/${props.room.match_id}/score`, { method: 'POST', headers: { 'X-Room-Token': props.token },
      body: JSON.stringify(props.room.solo ? { nickname: nickname.value.trim() } : {}) });
    submittedName.value = result.nickname; sessionStorage.setItem(submissionKey, result.nickname);
    message.success('已提交成绩，同昵称保留最佳成绩');
  } catch (error) { message.error((error as Error).message); }
  finally { busy.value = false; }
}
</script>
<template>
  <section aria-labelledby="public-score-title" class="upload">
    <h2 id="public-score-title">公开成绩</h2>
    <strong v-if="!room.history && player.public_correct !== player.correct">房内答对 {{ player.correct }} 题 · 公开成绩 {{ player.public_correct }} 题</strong>
    <form @submit.prevent="upload"><label v-if="room.solo">上榜昵称<n-input :value="submittedName || nickname" :disabled="!!submittedName || busy" :maxlength="24" :input-props="{ autocomplete: 'nickname' }" @update:value="nickname = $event" /></label>
      <n-button attr-type="submit" :disabled="!!submittedName || (room.solo && !nickname.trim())" :loading="busy">{{ submittedName ? '成绩已提交' : '上传个人成绩' }}</n-button></form>
    <section v-if="submittedName" class="preview" aria-labelledby="preview-title"><h3 id="preview-title">榜单前五</h3>
      <p v-if="error" role="alert">{{ error }} <n-button @click="retry++">重试</n-button></p>
      <GameBoardRecords v-else-if="board" :board="board" :limit="5" />
      <p v-else role="status">正在读取榜单…</p>
    </section>
  </section>
</template>
<style scoped>
.upload { display: grid; gap: 12px; border-top: 1px solid var(--line); padding-top: 20px; margin-top: 24px; }
form { display: flex; align-items: end; flex-wrap: wrap; gap: 8px; }
label, .preview { display: grid; gap: 4px; }
label { width: min(16rem, 100%); }
.preview { margin-top: 8px; gap: 8px; }
@media (max-width: 599px) { label { flex: 1; min-width: min(10em, 100%); } }
</style>
