<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { ArrowLeft, Copy, RotateCcw } from '@lucide/vue';
import { NAlert, NButton, NCheckbox, NInput, useMessage } from 'naive-ui';
import { filterOnlyQuery, fromQuery, type Filter } from './filters';
import { rangeError } from './date-range';
import { useGameRoom, type Settings } from './use-game-room';
import { useLibrary } from './store';
import { usePageTitle } from './page-title';
import GameBoard from './GameBoard.vue';
import { averageCells, compareGrid, faceDisplay } from './face-grid';
import GameRoomSettings from './GameRoomSettings.vue';
import RoomPersonalResult from './RoomPersonalResult.vue';
import GameFilterEditor from './GameFilterEditor.vue';
import GameFilterSummary from './GameFilterSummary.vue';
import GameRoomSources from './GameRoomSources.vue';
import PersonSelect from './PersonSelect.vue';
import HistoryBoard from './HistoryBoard.vue';
import { average, dayLabel, difference, middleDay } from './history-quiz';

const props = defineProps<{ history?: boolean }>();
const gamePath = props.history ? '/history-quiz' : '/face-game';
const route = useRoute(), toast = useMessage(), library = useLibrary();
const { code, token, room, busy, error, syncError, seconds, gridStarted, enter, act } = useGameRoom(props.history);
usePageTitle(() => code.value ? `对战房间 ${code.value}` : '多人对战');
const filters = ref(fromQuery(route.query)), draftFilters = ref(filters.value);
watch(() => route.query, value => { filters.value = fromQuery(value); });
const activeFilter = computed(() => room.value ? fromQuery(room.value.filters) : filters.value);
const query = computed(() => filterOnlyQuery(activeFilter.value));
const roomFilters = (value: Filter) => ({ ...filterOnlyQuery(value), include_no_faces: value.include_no_faces });
const nickname = ref(sessionStorage.getItem('face-room:name') || ''), joinCode = ref(''), joining = ref(false);
const settingsKey = props.history ? 'history-room:settings' : 'face-room:settings';
function loadSettings(): Settings {
  const defaults = { ...faceDisplay(null, !props.history), single_life: false, answer_seconds: 15, continue_seconds: 10 };
  try {
    const saved = JSON.parse(localStorage.getItem(settingsKey) ?? 'null');
    if (!saved || typeof saved !== 'object') return defaults;
    if (!props.history) {
      Object.assign(defaults, faceDisplay(saved));
      defaults.single_life = !defaults.grid && saved.single_life === true;
    }
    for (const [key, minimum] of [['answer_seconds', 3], ['continue_seconds', 0]] as const) {
      if (Number.isInteger(saved[key]) && saved[key] >= minimum && saved[key] <= 300) defaults[key] = saved[key];
    }
  } catch { return defaults; }
  return defaults;
}
const settings = ref(loadSettings()), draftSettings = ref<Settings>({ ...settings.value });
watch(settings, value => {
  try { localStorage.setItem(settingsKey, JSON.stringify(value)); } catch { return; }
});
const person = ref<number | null>(null), notFace = ref(false), content = ref(''), editing = ref(false), showLink = ref(false);
const me = computed(() => room.value?.players.find(player => player.id === room.value?.me));
const host = computed(() => me.value?.id === room.value?.host);
const online = computed(() => room.value?.players.filter(player => player.online).length ?? 0);
const record = computed(() => room.value?.history);
const deviation = (id: number) => record.value?.total_deviations[id] ?? 0;
type Player = NonNullable<typeof room.value>['players'][number];
function compare(first: Player, second: Player) {
  if (record.value) return deviation(first.id) - deviation(second.id);
  if (room.value?.settings.grid) return compareGrid(first, second);
  return Number(first.eliminated) - Number(second.eliminated) || second.correct - first.correct;
}
const ranking = computed(() => [...(room.value?.players ?? [])].sort((first, second) => compare(first, second) || first.id - second.id));
function rank(player: (typeof ranking.value)[number]) {
  return ranking.value.findIndex(item => compare(item, player) === 0) + 1;
}
const myRank = computed(() => me.value ? rank(me.value) : 0);
const tied = computed(() => ranking.value.some(player => player.id !== me.value?.id && rank(player) === myRank.value));
const survivors = computed(() => ranking.value.filter(player => !player.eliminated));
const lastRound = computed(() => room.value?.settings.single_life && survivors.value.length <= 1);
const voteName = computed(() => room.value?.proposal?.suggested_name || (room.value?.proposal?.not_face ? '不是人脸' : '无法确定人物'));
const proposer = computed(() => room.value?.players.find(player => player.id === room.value?.proposer)?.name);
const invite = computed(() => `${location.origin}${gamePath}/rooms/${code.value}`);
const phaseName = { lobby: '等待开局', loading: '等待玩家加载照片', answer: '答题中', reveal: '答案揭晓', draft: '填写反馈', vote: '反馈投票', waiting: '等待出题', finished: '最终排名' };
const inRound = computed(() => room.value && !['lobby', 'finished'].includes(room.value.phase));
const showGuess = computed(() => room.value?.phase !== 'finished' && !!record.value?.correct_date);
const showRank = computed(() => room.value?.phase !== 'lobby' && (!record.value || record.value.settled > 0));
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
  else if (!rangeError(filters.value.start, filters.value.end)) void enter(name, '', { settings: settings.value, filters: roomFilters(filters.value) });
}
async function copyInvite() {
  try { await navigator.clipboard.writeText(invite.value); toast.success('已复制邀请链接'); }
  catch { showLink.value = true; }
}
function editSettings() {
  if (!room.value) return;
  draftSettings.value = { ...room.value.settings }; draftFilters.value = fromQuery(room.value.filters); editing.value = true;
}
async function saveSettings() {
  await act('settings', { settings: draftSettings.value, filters: roomFilters(draftFilters.value) });
  if (!error.value && room.value) {
    settings.value = { ...room.value.settings };
    editing.value = false;
  }
}
</script>

<template>
  <main class="room-page" :class="{ 'game-start': !token || !inRound }">
    <header v-if="inRound && room" class="round-bar"><h1>{{ room.round ? `第 ${room.round} 题 · ` : '' }}{{ phaseName[room.phase] }}</h1><strong v-if="seconds !== null" role="timer">{{ seconds }} 秒</strong></header>
    <header v-else><h1>{{ history ? '史官测验 · 多人对战' : '多人对战' }}</h1><router-link :to="{ path: gamePath, query }"><ArrowLeft :size="16" />单人游戏</router-link></header>
    <n-alert v-if="error" type="error" role="alert" closable @close="error = ''">{{ error }}</n-alert>
    <p v-if="syncError" role="status">{{ syncError }}</p>
    <form v-if="!token" class="entry setup-entry" @submit.prevent="enterRoom">
      <h2 v-if="code">加入房间 {{ code }}</h2>
      <div v-else class="tabs" aria-label="对战入口"><button type="button" :aria-pressed="!joining" @click="joining = false">创建房间</button><button type="button" :aria-pressed="joining" @click="joining = true">加入房间</button></div>
      <div class="setup-columns"><div class="setup-fields">
      <label>昵称<n-input v-model:value="nickname" :maxlength="24" placeholder="你的昵称" :input-props="{ 'aria-label': '昵称', autocomplete: 'nickname' }" /></label>
      <label v-if="joining && !code">房间码<n-input v-model:value="joinCode" :maxlength="6" placeholder="6 位房间码" :input-props="{ 'aria-label': '房间码', autocapitalize: 'characters' }" /></label>
      <GameRoomSettings v-if="!isJoin" v-model="settings" :history="history" />
      </div><GameFilterEditor v-if="!isJoin" v-model="filters" :face="!history" /></div>
      <n-button type="primary" attr-type="submit" :loading="busy" :disabled="!nickname.trim() || (isJoin ? !code && joinCode.trim().length !== 6 : !!rangeError(filters.start, filters.end))">{{ isJoin ? '进入房间' : '创建并进入' }}</n-button>
    </form>
    <p v-else-if="!room" role="status">正在连接房间…</p>
    <template v-else>
      <div v-if="me && inRound" class="my-record" role="group" aria-label="我的战绩"><strong>我的战绩</strong>
        <template v-if="record"><span>平均偏差 {{ average(deviation(me.id), record.settled) }}</span><span>已结算 {{ record.settled }} 题 · 未答 {{ me.unanswered }}</span></template>
        <template v-else-if="room.settings.grid"><strong>{{ me.correct - me.wrong }} 分</strong><span>正确 {{ me.correct }}</span><span>错误 {{ me.wrong }}</span><span>答对时平均 {{ averageCells(me.correct_cells ?? 0, me.correct) }}</span></template>
        <template v-else-if="room.settings.single_life"><span>已通过 {{ me.correct }} 题</span><small>{{ me.eliminated ? '已淘汰' : '存活' }} · 剩余 {{ survivors.length }} 人</small></template>
        <template v-else><span>正确 {{ me.correct }}</span><span>错误 {{ me.wrong }}</span><span>未答 {{ me.unanswered }}</span></template>
      </div>
      <section v-if="room.phase === 'lobby'" class="entry" :class="{ 'setup-entry': editing }">
        <h2>等待开局 · {{ online }}/12 人</h2>
        <template v-if="editing"><div class="setup-columns"><GameRoomSettings v-model="draftSettings" :history="history" /><GameFilterEditor v-model="draftFilters" :face="!history" /></div><div class="actions"><n-button type="primary" :disabled="busy || !!rangeError(draftFilters.start, draftFilters.end)" @click="saveSettings">保存设置</n-button><n-button quaternary @click="editing = false">取消</n-button></div></template>
        <template v-else><p>{{ room.settings.grid ? `逐格显示 · ${room.settings.grid_size}×${room.settings.grid_size} · 每格 ${room.settings.grid_seconds} 秒 · 不限时抢答` : `${room.settings.cropped ? '截取人脸' : '显示全图'} · 每题 ${room.settings.answer_seconds} 秒` }} · {{ room.settings.continue_seconds ? `${room.settings.continue_seconds} 秒后切题` : '全员继续后切题' }}</p>
          <p v-if="room.settings.single_life">一命模式 · 答错或未答即淘汰，开局后不可加入</p>
          <div v-if="host" class="actions"><n-button type="primary" :disabled="busy || online < 2" @click="act('start')">开始对战</n-button><n-button :disabled="busy" @click="editSettings">修改设置</n-button></div>
          <p v-else>等待房主开始对战</p></template>
        <GameFilterSummary v-if="!editing" :filter="activeFilter" />
      </section>
      <template v-else-if="room.phase !== 'finished'">
        <div v-if="room.phase === 'waiting'" class="actions"><p role="status">{{ room.message }}</p><n-button v-if="host" :disabled="busy || online < 2" @click="act('start')">重新出题</n-button></div>
        <HistoryBoard v-else-if="record?.photo" :key="room.round" :photo="record.photo" :selected="record.my_guess" :correct="record.correct_date"
          :unanswered="!!record.correct_date && !me?.answered" :locked="busy || room.phase !== 'answer' || !me?.playing || me.answered" @choose="guess_date => act('answer', { guess_date })">
          <p v-if="!me?.playing" role="status">你将从下一题起参赛</p>
          <p v-else-if="room.phase === 'answer' && me.answered" role="status">已提交，等待揭晓</p>
          <n-button v-if="room.phase === 'reveal' && me?.playing" type="primary" :disabled="busy || me.ready" @click="act('ready')">{{ me.ready ? '已准备继续' : '继续' }}</n-button>
          <GameRoomSources v-if="room.source_photo" :group-id="room.source_photo.group_id" :image-id="room.source_photo.image_id" :query="query" />
        </HistoryBoard>
        <GameBoard v-else-if="room.photo" v-slot="{ gridComplete }" :key="room.round" :photo="room.photo" :cropped="room.settings.cropped" :revealed="room.phase !== 'loading' && room.phase !== 'answer'" @loaded="act('image_loaded')"
          :order="room.grid?.order" :started="gridStarted" :interval="room.settings.grid_seconds" :wrong-choices="room.grid?.wrong_choices" :correct-cells="room.grid?.correct_cells"
          :locked="busy || room.phase !== 'answer' || !me?.playing || me.answered || !!room.grid?.gave_up" :selected="me?.answered ? room.choice : undefined"
          :correct-id="room.correct_choice" :voided="room.void" :tallies="room.tallies" :answer-name="room.accepted ? room.proposal?.suggested_name : room.answer_name" @choose="choice => act('answer', { choice })">
          <p v-if="!me?.playing" role="status">{{ me?.eliminated ? '已淘汰，正在观战' : '你将从下一题起参赛' }}</p>
          <div v-else-if="room.grid && room.phase === 'answer'" class="grid-answer-help">
            <p role="status">{{ room.grid.gave_up ? '已放弃本题，等待其他玩家' : '答对 +1 分，答错 −1 分，可继续抢答' }}</p>
            <n-button v-if="gridComplete && !room.grid.gave_up" :disabled="busy" @click="act('give_up')">放弃作答</n-button>
          </div>
          <p v-else-if="room.phase === 'answer'" role="status">{{ me.answered ? '已提交，等待揭晓' : '请选择答案' }} · {{ room.players.filter(player => player.answered).length }}/{{ room.players.filter(player => player.playing).length }} 人已答</p>
          <div v-if="room.phase === 'reveal' && me?.playing" class="actions round-actions"><n-button type="primary" :disabled="busy || me.ready" @click="act('ready')">{{ me.ready ? '已准备继续' : lastRound ? '确认结算' : '继续' }}</n-button><n-button v-if="room.accepted === null" :disabled="busy" @click="act('draft')">我要反馈</n-button></div>
          <p v-if="room.phase !== 'loading' && room.phase !== 'answer'" role="status">图库答案：{{ room.answer_name }}<template v-if="room.accepted !== null"> · {{ room.accepted ? (room.void ? '反馈已采纳，本题不计分' : `反馈已采纳，按${voteName}计分`) : '反馈未通过，保留原判' }}</template></p>
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
        <span class="spacer" /><router-link v-if="inRound" :to="{ path: gamePath, query }">单人游戏</router-link><n-button quaternary :disabled="busy" @click="act('leave')">离开房间</n-button></div>
      <n-input v-if="showLink" readonly :value="invite" :input-props="{ 'aria-label': '邀请链接' }" />
      <RoomPersonalResult v-if="me && room.phase === 'finished'" :room="room" :player="me" :rank="showRank ? myRank : null" :tied="tied" />
      <section class="standings"><div class="standings-heading"><h2>{{ room.phase === 'finished' ? '最终排名' : room.phase === 'lobby' ? '房间成员' : '排行榜' }}</h2>
        <n-button v-if="host && room.phase === 'finished'" type="primary" :disabled="busy" @click="act('restart')"><RotateCcw :size="16" aria-hidden="true" />再来一局</n-button></div>
        <p v-if="room.phase === 'finished' && lastRound">{{ survivors.length ? `获胜：${survivors[0]!.name}` : '无人存活' }}</p>
        <table aria-label="房间排行榜"><thead><tr><th v-if="showRank" class="place-col" scope="col">名次</th><th class="player-col" scope="col">玩家</th><template v-if="record"><th v-if="showGuess" scope="col">本题猜测</th><th scope="col">平均偏差</th><th scope="col">未答</th></template><th v-else-if="room.settings.single_life" scope="col">通过题数</th><template v-else><th v-if="room.settings.grid" scope="col">分数</th><th scope="col">正确</th><th scope="col">错误</th><th scope="col">{{ room.settings.grid ? '平均格数' : '未答' }}</th></template></tr></thead>
          <tbody><tr v-for="player in ranking" :key="player.id" :class="{ 'own-row': player.id === room.me }"><td v-if="showRank" class="place-col">{{ rank(player) }}</td><th scope="row" class="player-col">{{ player.name }}
            <small>{{ [player.id === room.me ? '你' : '', player.id === room.host ? '房主' : '', player.eliminated ? '已淘汰' : '', !player.online ? '离线' : '', player.ready && room.phase === 'reveal' ? '已准备' : ''].filter(Boolean).join(' · ') }}</small></th>
            <template v-if="record"><td v-if="showGuess && record.photo && record.correct_date"><span>{{ record.guesses?.[player.id] ?? '未答（按居中日期计）' }}</span><small>{{ difference(record.guesses?.[player.id] ?? dayLabel(middleDay(record.photo)), record.correct_date) }}</small></td><td>{{ average(deviation(player.id), record.settled) }}</td><td>{{ player.unanswered }}</td></template>
            <template v-else><td v-if="room.settings.grid">{{ player.correct - player.wrong }}</td><td>{{ player.correct }}</td><template v-if="!room.settings.single_life"><td>{{ player.wrong }}</td><td>{{ room.settings.grid ? averageCells(player.correct_cells ?? 0, player.correct) : player.unanswered }}</td></template></template></tr></tbody></table>
        <n-button v-if="host && inRound" :disabled="busy || room.ending" @click="act('finish')">{{ room.ending ? '投票结束后结算' : '结束对战' }}</n-button>
        <GameFilterSummary v-if="room.phase === 'finished'" :filter="activeFilter" />
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
.setup-entry { max-width: none; gap: 20px; }
.setup-columns, .setup-fields { display: grid; gap: 20px; align-content: start; min-width: 0; }
.setup-fields > label { display: grid; gap: 6px; }
@media (min-width: 760px) {
  .setup-columns { grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr); align-items: start; gap: 48px; }
  .setup-columns > .game-filters { border-block: 0; }
}
.entry > button { justify-self: start; }
.setup-entry > button { min-width: 8rem; }
@media (max-width: 599px) { .setup-entry > button { justify-self: stretch; } }
.tabs { border-bottom: 1px solid var(--line); }
.tabs button { min-height: 44px; background: transparent; border: 0; border-bottom: 2px solid transparent; color: var(--muted); padding: 0 8px; }
.tabs button[aria-pressed=true] { color: var(--accent); border-color: var(--accent); }
.round-bar { min-height: 44px; font-variant-numeric: tabular-nums; }
.round-bar + .my-record { margin: 0 0 8px; padding-bottom: 8px; border-bottom: 1px solid var(--line); }
.round-actions { margin: 8px 0; }
.grid-answer-help { display: grid; justify-items: start; gap: 8px; margin-block-start: 12px; }
.room-bar a { display: inline-flex; align-items: center; min-height: 44px; }
.actions { flex-wrap: wrap; }
.feedback p, .entry p, small, .rank { color: var(--muted); }
.proposal { white-space: pre-wrap; overflow-wrap: anywhere; }
.standings { padding-top: 20px; max-width: 960px; }
.standings-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.my-record { flex-wrap: wrap; margin-top: 12px; font-variant-numeric: tabular-nums; }
.standings table { width: 100%; border-collapse: collapse; margin: 8px 0 20px; font-variant-numeric: tabular-nums; }
.standings th, .standings td { padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: end; }
.standings thead th { font-size: .875rem; color: var(--muted); white-space: nowrap; }
.standings .player-col { text-align: start; overflow-wrap: anywhere; }
.standings .place-col { width: 4em; text-align: center; }
.standings .own-row { background: var(--selection); }
.standings small { display: block; font-weight: normal; }
@media (max-width: 768px) {
  .room-page { --game-control-reserve: 31rem; padding: 4px 16px 28px; }
  .standings th, .standings td { padding: 8px 6px; }
  .standings .place-col { width: 3em; }
  .round-actions button { flex: 1; }
}
</style>
