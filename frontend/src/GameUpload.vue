<script setup lang="ts">
import { computed, ref } from 'vue';
import { NButton, NInput, useMessage } from 'naive-ui';
import { api } from './api';
import type { RoomView } from './use-game-room';
import type { components } from './schema';

const props = defineProps<{ room: RoomView; token: string; gamePath: string }>();
const player = computed(() => props.room.players.find(member => member.id === props.room.me)!);
const name = defineModel<string>('nickname', { required: true });
const busy = ref(false), uploaded = ref(false), message = useMessage();
async function upload() {
  busy.value = true;
  try {
    await api<components['schemas']['Record']>(`${props.gamePath}/matches/${props.room.match_id}/score`, { method: 'POST', headers: { 'X-Room-Token': props.token },
      body: JSON.stringify(props.room.solo ? { nickname: name.value.trim() } : {}) });
    uploaded.value = true; message.success('已提交成绩，同昵称保留最佳成绩');
  } catch (error) { message.error((error as Error).message); }
  finally { busy.value = false; }
}
</script>
<template>
  <section aria-label="公开成绩" class="upload">
    <strong v-if="!room.history && player.eligible && player.public_correct !== player.correct">房内答对 {{ player.correct }} 题 · 公开成绩 {{ player.public_correct }} 题</strong>
    <form v-if="player.eligible" @submit.prevent="upload"><label v-if="room.solo">上榜昵称<n-input v-model:value="name" :disabled="uploaded" :maxlength="24" /></label>
      <n-button attr-type="submit" :disabled="uploaded || (room.solo && !name.trim())" :loading="busy">{{ uploaded ? '成绩已提交' : '上传个人成绩' }}</n-button></form>
    <p v-else>本局不参与公开排名</p>
  </section>
</template>
<style scoped>
.upload { margin-block: 16px; }
form, label { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
label .n-input { width: 11em; }
</style>
