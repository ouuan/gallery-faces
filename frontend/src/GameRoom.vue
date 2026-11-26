<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { ArrowLeft, Copy, RotateCcw } from '@lucide/vue';
import { NAlert, NButton, NCheckbox, NInput, useMessage } from 'naive-ui';
import { filterOnlyQuery, fromQuery } from './filters';
import { useGameRoom, type Settings } from './use-game-room';
import { useLibrary } from './store';
import { usePageTitle } from './page-title';
import GameBoard from './GameBoard.vue';
import GameRoomSettings from './GameRoomSettings.vue';
import GameRoomFilters from './GameRoomFilters.vue';
import GameRoomSources from './GameRoomSources.vue';
import PersonSelect from './PersonSelect.vue';

const route = useRoute(), toast = useMessage(), library = useLibrary();
const { code, token, room, busy, error, syncError, seconds, enter, act } = useGameRoom();
usePageTitle(() => code.value ? `对战房间 ${code.value}` : '多人对战');
const query = computed(() => filterOnlyQuery(fromQuery(route.query)));
const nickname = ref(sessionStorage.getItem('face-room:name') || ''), joinCode = ref(''), joining = ref(false);
const settings = ref<Settings>({ cropped: false, single_life: false, answer_seconds: 15, continue_seconds: 10 });
const person = ref<number | null>(null), notFace = ref(false), content = ref(''), editing = ref(false), showLink = ref(false);
const me = computed(() => room.value?.players.find(player => player.id === room.value?.me));
const host = computed(() => me.value?.id === room.value?.host);
const online = computed(() => room.value?.players.filter(player => player.online).length ?? 0);
const ranking = computed(() => [...(room.value?.players ?? [])].sort((first, second) => Number(first.eliminated) - Number(second.eliminated) || second.correct - first.correct || first.id - second.id));
const survivors = computed(() => ranking.value.filter(player => !player.eliminated));
const lastRound = computed(() => room.value?.settings.single_life && survivors.value.length <= 1);
const voteName = computed(() => room.value?.proposal?.suggested_name || (room.value?.proposal?.not_face ? '不是人脸' : '无法确定人物'));
const proposer = computed(() => room.value?.players.find(player => player.id === room.value?.proposer)?.name);
const invite = computed(() => `${location.origin}/face-game/rooms/${code.value}`);
const phaseName = { lobby: '等待开局', answer: '答题中', reveal: '答案揭晓', draft: '填写反馈', vote: '反馈投票', waiting: '等待出题', finished: '最终排名' };
const inRound = computed(() => room.value && !['lobby', 'finished'].includes(room.value.phase));
const isJoin = computed(() => Boolean(code.value) || joining.value);
watch(() => room.value?.phase, phase => {
  editing.value = false;
  if (phase === 'draft') {
    person.value = null; notFace.value = false; content.value = '';
    library.load().catch(cause => { error.value = (cause as Error).message; });
  }
});
function enterRoom() {
  const name = nickname.value.trim();
  if (!name) return;
  sessionStorage.setItem('face-room:name', name);
  if (isJoin.value) void enter(name, code.value || joinCode.value.trim().toUpperCase());
  else void enter(name, '', { settings: settings.value, filters: { ...query.value, include_no_faces: query.value.include_no_faces === 'true' } });
}
async function copyInvite() {
  try { await navigator.clipboard.writeText(invite.value); toast.success('已复制邀请链接'); }
  catch { showLink.value = true; }
}
function editSettings() {
  if (!room.value) return;
  settings.value = { ...room.value.settings }; editing.value = true;
}
async function saveSettings() {
  await act('settings', { settings: settings.value });
  if (!error.value) editing.value = false;
}
</script>

<template>
  <main class="room-page">
    <header v-if="inRound && room" class="round-bar"><h1>{{ room.round ? `第 ${room.round} 题 · ` : '' }}{{ phaseName[room.phase] }}</h1><strong v-if="seconds !== null" role="timer">{{ seconds }} 秒</strong></header>
    <header v-else><h1>多人对战</h1><router-link :to="{ path: '/face-game', query }"><ArrowLeft :size="16" />单人游戏</router-link></header>
    <n-alert v-if="error" type="error" role="alert" closable @close="error = ''">{{ error }}</n-alert>
    <p v-if="syncError" role="status">{{ syncError }}</p>
    <form v-if="!token" class="entry" @submit.prevent="enterRoom">
      <h2 v-if="code">加入房间 {{ code }}</h2>
      <div v-else class="tabs" aria-label="对战入口"><button type="button" :aria-pressed="!joining" @click="joining = false">创建房间</button><button type="button" :aria-pressed="joining" @click="joining = true">加入房间</button></div>
      <label>昵称<n-input v-model:value="nickname" :maxlength="24" placeholder="你的昵称" :input-props="{ 'aria-label': '昵称', autocomplete: 'nickname' }" /></label>
      <label v-if="joining && !code">房间码<n-input v-model:value="joinCode" :maxlength="6" placeholder="6 位房间码" :input-props="{ 'aria-label': '房间码', autocapitalize: 'characters' }" /></label>
      <GameRoomSettings v-if="!isJoin" v-model="settings" />
      <n-button type="primary" attr-type="submit" :loading="busy" :disabled="!nickname.trim() || (isJoin && !code && joinCode.trim().length !== 6)">{{ isJoin ? '进入房间' : '创建并进入' }}</n-button>
    </form>
    <p v-else-if="!room" role="status">正在连接房间…</p>
    <template v-else>
      <div v-if="me && room.phase !== 'lobby'" class="my-record" role="group" aria-label="我的战绩"><strong>我的战绩</strong>
        <template v-if="room.settings.single_life"><span>已通过 {{ me.correct }} 题</span><small>{{ me.eliminated ? '已淘汰' : '存活' }} · 剩余 {{ survivors.length }} 人</small></template>
        <template v-else><span>正确 {{ me.correct }}</span><span>错误 {{ me.wrong }}</span><span>未答 {{ me.unanswered }}</span></template>
      </div>
      <section v-if="room.phase === 'lobby'" class="entry">
        <h2>等待开局 · {{ online }}/12 人</h2>
        <template v-if="editing"><GameRoomSettings v-model="settings" /><div class="actions"><n-button :disabled="busy" @click="saveSettings">保存设置</n-button><n-button quaternary @click="editing = false">取消</n-button></div></template>
        <template v-else><p>{{ room.settings.cropped ? '截取人脸' : '显示全图' }} · 每题 {{ room.settings.answer_seconds }} 秒 · {{ room.settings.continue_seconds ? `${room.settings.continue_seconds} 秒后切题` : '全员继续后切题' }}</p>
          <p v-if="room.settings.single_life">一命模式 · 答错或未答即淘汰，开局后不可加入</p>
          <div v-if="host" class="actions"><n-button type="primary" :disabled="busy || online < 2" @click="act('start')">开始对战</n-button><n-button :disabled="busy" @click="editSettings">修改设置</n-button></div>
          <p v-else>等待房主开始对战</p></template>
        <GameRoomFilters :filters="room.filters" />
      </section>
      <template v-else-if="room.phase !== 'finished'">
        <div v-if="room.phase === 'waiting'" class="actions"><p role="status">{{ room.message }}</p><n-button v-if="host" :disabled="busy || online < 2" @click="act('start')">重新出题</n-button></div>
        <GameBoard v-else-if="room.photo" :key="room.round" :photo="room.photo" :cropped="room.settings.cropped" :revealed="room.phase !== 'answer'"
          :locked="busy || room.phase !== 'answer' || !me?.playing || me.answered" :selected="me?.answered ? room.choice : undefined"
          :correct-id="room.correct_choice" :voided="room.void" :tallies="room.tallies" :answer-name="room.accepted ? room.proposal?.suggested_name : room.answer_name" @choose="choice => act('answer', { choice })">
          <p v-if="!me?.playing" role="status">{{ me?.eliminated ? '已淘汰，正在观战' : '你将从下一题起参赛' }}</p>
          <p v-else-if="room.phase === 'answer'" role="status">{{ me.answered ? '已提交，等待揭晓' : '请选择答案' }} · {{ room.players.filter(player => player.answered).length }}/{{ room.players.filter(player => player.playing).length }} 人已答</p>
          <div v-if="room.phase === 'reveal' && me?.playing" class="actions round-actions"><n-button type="primary" :disabled="busy || me.ready" @click="act('ready')">{{ me.ready ? '已准备继续' : lastRound ? '确认结算' : '继续' }}</n-button><n-button v-if="room.accepted === null" :disabled="busy" @click="act('draft')">我要反馈</n-button></div>
          <p v-if="room.phase !== 'answer'" role="status">图库答案：{{ room.answer_name }}<template v-if="room.accepted !== null"> · {{ room.accepted ? (room.void ? '反馈已采纳，本题不计分' : `反馈已采纳，按${voteName}计分`) : '反馈未通过，保留原判' }}</template></p>
          <p v-if="lastRound && room.phase === 'reveal'" role="status">本题结算后结束对战</p>
          <template v-if="room.phase === 'draft'"><p role="status">{{ proposer }} 正在填写反馈，已暂停切题</p>
            <form v-if="room.proposer === room.me" class="feedback" @submit.prevent="act('submit', { suggested_person_id: notFace ? null : person, not_face: notFace, content })">
              <PersonSelect v-model="person" :disabled="notFace" accessible-label="建议人物" placeholder="建议人物（可不选）" />
              <n-checkbox v-model:checked="notFace">不是人脸</n-checkbox><n-input v-model:value="content" type="textarea" :maxlength="1000" placeholder="补充说明（可不填）" :input-props="{ 'aria-label': '补充说明' }" />
              <p>提交后，全房可见，并会送交管理员审核</p><div class="actions"><n-button type="primary" attr-type="submit" :disabled="busy">提交反馈</n-button><n-button :disabled="busy" @click="act('cancel')">取消反馈</n-button></div>
            </form></template>
          <template v-if="room.proposal"><p class="proposal">{{ proposer }} 提议：{{ voteName }}<template v-if="room.proposal.content"><br />{{ room.proposal.content }}</template></p>
            <p>赞成 {{ room.votes_for }} · 反对 {{ room.votes_against }}</p>
            <div v-if="room.phase === 'vote' && me?.playing && !room.voted" class="actions"><n-button type="primary" :disabled="busy" @click="act('vote', { support: true })">赞成</n-button><n-button :disabled="busy" @click="act('vote', { support: false })">反对</n-button></div>
            <p v-else-if="room.phase === 'vote' && room.voted" role="status">已投票，等待结果</p></template>
          <GameRoomSources v-if="room.source_photo" :group-id="room.source_photo.group_id" :image-id="room.source_photo.image_id" :query="query" />
        </GameBoard>
      </template>
      <div class="room-bar"><strong>房间 <span class="code">{{ room.code }}</span></strong>
        <n-button v-if="room.phase !== 'finished' && !(room.settings.single_life && room.round)" quaternary @click="copyInvite"><Copy :size="15" />复制邀请链接</n-button>
        <span class="spacer" /><router-link v-if="inRound" :to="{ path: '/face-game', query }">单人游戏</router-link><n-button quaternary :disabled="busy" @click="act('leave')">离开房间</n-button></div>
      <n-input v-if="showLink" readonly :value="invite" :input-props="{ 'aria-label': '邀请链接' }" />
      <section class="standings"><div class="standings-heading"><h2>{{ room.phase === 'finished' ? '最终排名' : room.phase === 'lobby' ? '房间成员' : '排行榜' }}</h2>
        <n-button v-if="host && room.phase === 'finished'" type="primary" :disabled="busy" @click="act('restart')"><RotateCcw :size="16" aria-hidden="true" />重新开始</n-button></div>
        <p v-if="room.phase === 'finished' && lastRound">{{ survivors.length ? `获胜：${survivors[0]!.name}` : '无人存活' }}</p>
        <table aria-label="房间排行榜"><thead><tr><th scope="col">玩家</th><th v-if="room.settings.single_life" scope="col">通过题数</th><template v-else><th scope="col">正确</th><th scope="col">错误</th><th scope="col">未答</th></template></tr></thead>
          <tbody><tr v-for="player in ranking" :key="player.id"><th scope="row"><span v-if="room.phase !== 'lobby'" class="rank">{{ ranking.findIndex(item => item.eliminated === player.eliminated && item.correct === player.correct) + 1 }}.</span> {{ player.name }}
            <small>{{ [player.id === room.me ? '你' : '', player.id === room.host ? '房主' : '', player.eliminated ? '已淘汰' : '', !player.online ? '离线' : '', player.ready && room.phase === 'reveal' ? '已准备' : ''].filter(Boolean).join(' · ') }}</small></th>
            <td>{{ player.correct }}</td><template v-if="!room.settings.single_life"><td>{{ player.wrong }}</td><td>{{ player.unanswered }}</td></template></tr></tbody></table>
        <n-button v-if="host && inRound" :disabled="busy || room.ending" @click="act('finish')">{{ room.ending ? '投票结束后结算' : '结束对战' }}</n-button>
      </section>
    </template>
  </main>
</template>

<style scoped>
.room-page { width: min(100%, 1440px); margin: auto; padding: 20px 28px 40px; }
header, header a, .room-bar, .round-bar, .actions, .tabs, .my-record { display: flex; align-items: center; gap: 10px; }
header, .round-bar { justify-content: space-between; }
header a, .room-bar button, .actions button, .entry > button, .standings > button { min-height: 44px; }
.room-bar { flex-wrap: wrap; border-bottom: 1px solid var(--line); padding: 4px 0; }
.code { font-variant-numeric: tabular-nums; user-select: all; }
.spacer { flex: 1; }
.entry, .feedback { display: grid; gap: 16px; max-width: 420px; margin: 20px 0; }
.entry > label { display: grid; gap: 4px; }
.entry > button { justify-self: start; }
.tabs { border-bottom: 1px solid var(--line); }
.tabs button { min-height: 44px; background: transparent; border: 0; border-bottom: 2px solid transparent; color: var(--muted); padding: 0 8px; }
.tabs button[aria-pressed=true] { color: var(--accent); border-color: var(--accent); }
.round-bar { min-height: 44px; font-variant-numeric: tabular-nums; }
.round-bar + .my-record { margin: 0 0 8px; padding-bottom: 8px; border-bottom: 1px solid var(--line); }
.round-actions { margin: 8px 0; }
.room-bar a { display: inline-flex; align-items: center; min-height: 44px; }
.actions { flex-wrap: wrap; }
.feedback p, .entry p, small, .rank { color: var(--muted); }
.proposal { white-space: pre-wrap; overflow-wrap: anywhere; }
.standings { padding-top: 16px; }
.standings-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; max-width: 520px; }
.my-record { flex-wrap: wrap; margin-top: 12px; font-variant-numeric: tabular-nums; }
.standings table { width: min(520px, 100%); border-collapse: collapse; margin: 8px 0 16px; font-variant-numeric: tabular-nums; }
.standings th, .standings td { padding: 8px 4px; border-bottom: 1px solid var(--line); text-align: end; }
.standings th:first-child { text-align: start; overflow-wrap: anywhere; } .standings th:not(:first-child) { width: 3.5em; white-space: nowrap; }
.standings small { display: block; font-weight: normal; }
@media (max-width: 768px) {
  .room-page { --game-control-reserve: 31rem; padding: 4px 16px 28px; }
  .round-actions button { flex: 1; }
}
</style>
