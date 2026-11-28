<script setup lang="ts">
import { computed, defineAsyncComponent, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { Copy, RotateCcw } from '@lucide/vue';
import { NAlert, NButton, NCheckbox, NInput, useMessage } from 'naive-ui';
import { filterOnlyQuery, fromQuery, type Filter } from './filters';
import { rangeError } from './date-range';
import { useGameRoom, type Settings } from './use-game-room';
import { useLibrary } from './store';
import { usePageTitle } from './page-title';
import GameBoard from './GameBoard.vue';
import { averageCells, compareGrid } from './face-grid';
import { parseRules, ruleQuery } from './game-rules';
import GameRoomSettings from './GameRoomSettings.vue';
import GameRoomRules from './GameRoomRules.vue';
import { api } from './api';
import type { components } from './schema';
import RoomPersonalResult from './RoomPersonalResult.vue';
import GameUpload from './GameUpload.vue';
import SoloGameResult from './SoloGameResult.vue';
import GameFilterEditor from './GameFilterEditor.vue';
import GameFilterSummary from './GameFilterSummary.vue';
import GameRoomSources from './GameRoomSources.vue';
import PersonSelect from './PersonSelect.vue';
import HistoryBoard from './HistoryBoard.vue';
import { average, closestResult, compareHistory, dayLabel, difference, formatPoints, middleDay } from './history-quiz';

const props = defineProps<{ history?: boolean; solo?: boolean }>();
const gamePath = props.history ? '/history-quiz' : '/face-game';
const route = useRoute(), router = useRouter(), toast = useMessage(), library = useLibrary();
const PostDetail = defineAsyncComponent(() => import('./PostDetail.vue'));
const postKey = computed(() => props.solo && typeof route.query.post === 'string' ? route.query.post : '');
const { code, token, room, busy, error, syncError, seconds, gridStarted, enter, act } = useGameRoom(props.history, props.solo);
const gameName = props.history ? '史官测验' : '认脸游戏';
usePageTitle(() => props.solo ? gameName : code.value ? `对战房间 ${code.value}` : '多人对战');
const filters = ref(fromQuery(route.query)), draftFilters = ref(filters.value);
const activeFilter = computed(() => room.value ? fromQuery(room.value.filters) : filters.value);
const query = computed(() => filterOnlyQuery(activeFilter.value));
const roomFilters = (value: Filter) => ({ ...filterOnlyQuery(value), include_no_faces: value.include_no_faces });
const nickname = ref(localStorage.getItem('game:nickname') ?? ''), joinCode = ref(''), joining = ref(false);
watch(nickname, value => localStorage.setItem('game:nickname', value.trim()));
const setupPath = props.solo ? gamePath : gamePath + '/rooms';
const settings = ref(parseRules(route.query, !!props.history)), draftSettings = ref<Settings>({ ...settings.value });
const activeSettings = computed(() => room.value?.settings ?? settings.value);
const rules = computed(() => ruleQuery(activeSettings.value, activeFilter.value, !!props.history));
const otherMode = computed(() => ({ path: props.solo ? gamePath + '/rooms' : gamePath,
  query: ruleQuery(activeSettings.value, activeFilter.value, !!props.history, !!props.solo) }));
const boardUnavailable = computed(() => !activeSettings.value.single_life && !activeSettings.value.round_limit ? '无尽模式不设榜单'
  : !props.solo && activeSettings.value.grid ? '多人逐格模式不参与公开排名' : '');
watch(() => route.fullPath, () => {
  if (route.path !== setupPath) return;
  const current = ruleQuery(settings.value, filters.value, !!props.history, !props.solo);
  if (router.resolve({ path: setupPath, query: current }).fullPath !== route.fullPath) {
    filters.value = fromQuery(route.query); settings.value = parseRules(route.query, !!props.history);
  }
});
watch(() => ruleQuery(settings.value, filters.value, !!props.history, !props.solo), value => {
  if (route.path === setupPath && router.resolve({ path: setupPath, query: value }).fullPath !== route.fullPath)
    void router.replace({ path: setupPath, query: value });
}, { immediate: true });
const person = ref<number | null>(null), notFace = ref(false), content = ref(''), editing = ref(false), showLink = ref(false);
const me = computed(() => room.value?.players.find(player => player.id === room.value?.me));
const host = computed(() => me.value?.id === room.value?.host);
const online = computed(() => room.value?.players.filter(player => player.online).length ?? 0);
const record = computed(() => room.value?.history);
const deviation = (id: number) => record.value?.total_deviations[id] ?? 0;
type Player = NonNullable<typeof room.value>['players'][number];
function compare(first: Player, second: Player) {
  if (record.value) return compareHistory(record.value, first.id, second.id);
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
const eliminationOver = computed(() => room.value?.settings.single_life && survivors.value.length < (props.solo ? 1 : 2));
const lastRound = computed(() => eliminationOver.value || (room.value && room.value.settings.round_limit > 0 && room.value.round >= room.value.settings.round_limit));
const readyLabel = computed(() => props.solo ? lastRound.value ? '查看结果' : '下一题' : lastRound.value ? (me.value?.ready ? '等待结算' : '确认结算') : (me.value?.ready ? '已准备继续' : '继续'));
const myAnswered = computed(() => record.value ? record.value.settled - (me.value?.unanswered ?? 0) : (me.value?.correct ?? 0) + (me.value?.wrong ?? 0));
const myAccuracy = computed(() => myAnswered.value > (me.value?.disputed ?? 0) ? `${Math.round(100 * (me.value?.correct ?? 0) / (myAnswered.value - (me.value?.disputed ?? 0)))}%` : '—');
const soloFeedback = computed(() => {
  const view = room.value;
  return (faceId: number | null, feedbackId: number) => {
    if (view && room.value?.stage === view.stage && view.accepted === null && me.value?.answered && view.choice !== view.correct_choice && faceId === view.revealed_face_id)
      void act('dispute', { feedback_id: feedbackId });
  };
});
const voteName = computed(() => room.value?.proposal?.suggested_name || (room.value?.proposal?.not_face ? '不是人脸' : '无法确定人物'));
const proposer = computed(() => room.value?.players.find(player => player.id === room.value?.proposer)?.name);
const invite = computed(() => `${location.origin}${gamePath}/rooms/${code.value}`);
const phaseName = { lobby: '等待开局', loading: props.solo ? '加载中' : '等待玩家加载照片', answer: '答题中', reveal: '答案揭晓', draft: '填写反馈', vote: '反馈投票', waiting: '等待出题', finished: '最终排名' };
const canInvite = computed(() => !props.solo && room.value && !room.value.ending && room.value.phase !== 'finished' && (!room.value.round || (room.value.settings.allow_late_join && !room.value.settings.single_life)));
const inRound = computed(() => room.value && !['lobby', 'finished'].includes(room.value.phase));
const showGuess = computed(() => room.value?.phase !== 'finished' && !!record.value?.correct_date);
const showRank = computed(() => room.value?.phase !== 'lobby' && (!record.value || record.value.settled > 0));
const isJoin = computed(() => Boolean(code.value) || joining.value);
const previewCode = computed(() => isJoin.value && !token.value ? code.value || joinCode.value.trim().toUpperCase() : '');
const preview = ref<components['schemas']['RoomPreview'] | null>(null), previewError = ref('');
watch(previewCode, async (target, _, cleanup) => {
  preview.value = null; previewError.value = '';
  if (target.length !== 6) return;
  const controller = new AbortController();
  cleanup(() => controller.abort());
  try {
    const result = await api<components['schemas']['RoomPreview']>(`${gamePath}/rooms/${encodeURIComponent(target)}/preview`, { signal: controller.signal });
    if (!controller.signal.aborted) preview.value = result;
  } catch (cause) { if (!controller.signal.aborted) previewError.value = (cause as Error).message; }
}, { immediate: true });
watch(() => room.value?.phase, phase => {
  editing.value = false;
  if (phase === 'draft') {
    person.value = null; notFace.value = false; content.value = '';
    library.load().catch(cause => { error.value = (cause as Error).message; });
  }
});
function enterRoom() {
  const name = nickname.value.trim() || (props.solo ? '我' : '');
  if (!name) return;
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
  if (await act('settings', { settings: draftSettings.value, filters: roomFilters(draftFilters.value) }) && room.value) {
    settings.value = { ...room.value.settings };
    editing.value = false;
  }
}
</script>

<template>
  <main class="room-page" :class="{ 'game-start': !token || !inRound }">
    <header v-if="inRound && room" class="round-bar"><h1><template v-if="room.round">第 {{ room.round }}<template v-if="room.settings.round_limit">/{{ room.settings.round_limit }}</template> 题 · </template>{{ phaseName[room.phase] }}</h1><strong v-if="seconds !== null" role="timer">{{ seconds }} 秒</strong></header>
    <header v-else class="game-heading"><h1>{{ solo ? gameName : history ? '史官测验 · 多人对战' : '多人对战' }}</h1><nav><router-link :to="otherMode">{{ solo ? '多人对战' : '单人游戏' }}</router-link><router-link :to="{ path: '/', query }">返回图库</router-link></nav></header>
    <n-alert v-if="error" type="error" role="alert" closable @close="error = ''">{{ error }}</n-alert>
    <p v-if="syncError" role="status">{{ syncError }}</p>
    <form v-if="!token" class="entry setup-entry" aria-label="开局设置" @submit.prevent="enterRoom">
      <h2 v-if="code">加入房间 {{ code }}</h2>
      <div v-else-if="!solo" class="tabs" aria-label="对战入口"><button type="button" :aria-pressed="!joining" @click="joining = false">创建房间</button><button type="button" :aria-pressed="joining" @click="joining = true">加入房间</button></div>
      <div class="setup-columns"><div class="setup-fields">
      <label>昵称<n-input v-model:value="nickname" :maxlength="24" :placeholder="solo ? '选填' : '你的昵称'" :input-props="{ 'aria-label': '昵称', autocomplete: 'nickname' }" /></label>
      <label v-if="joining && !code">房间码<n-input v-model:value="joinCode" :maxlength="6" placeholder="6 位房间码" :input-props="{ 'aria-label': '房间码', autocapitalize: 'characters' }" /></label>
      <GameRoomSettings v-if="!isJoin" v-model="settings" :history="history" :solo="solo" />
      </div><GameFilterEditor v-if="!isJoin" v-model="filters" :face="!history" />
      <div v-else-if="preview" class="setup-fields">
        <strong>{{ phaseName[preview.phase] }} · {{ preview.members }}/12 人</strong>
        <GameRoomRules :settings="preview.settings" :history="history" />
        <GameFilterSummary :filter="fromQuery(preview.filters)" />
      </div>
      <p v-else-if="previewCode.length === 6" role="status">{{ previewError || '正在读取房间信息…' }}</p></div>
      <n-button type="primary" attr-type="submit" :loading="busy" :disabled="(!solo && !nickname.trim()) || (isJoin ? !code && joinCode.trim().length !== 6 : !!rangeError(filters.start, filters.end))">{{ solo ? '开始游戏' : isJoin ? '进入房间' : '创建并进入' }}</n-button>
    </form>
    <p v-else-if="!room" role="status">正在连接房间…</p>
    <template v-else>
      <div v-if="me && solo && inRound" class="my-record" role="group" aria-label="本局统计">
        <strong>{{ record ? `平均偏差 ${average(deviation(me.id), record.settled)}` : `正确率 ${myAccuracy}` }}</strong><span>已答 {{ myAnswered }}<template v-if="room.settings.round_limit">/{{ room.settings.round_limit }}</template> 题</span>
        <template v-if="!record"><span>正确 {{ me.correct }}</span><span>错误 {{ me.wrong - (me.disputed ?? 0) }}</span><span>存疑 {{ me.disputed ?? 0 }}</span></template><span v-if="room.grid">答对时平均 {{ averageCells(me.correct_cells ?? 0, me.correct) }}</span>
      </div>
      <div v-else-if="me && inRound" class="my-record" role="group" aria-label="我的战绩"><strong>我的战绩</strong>
        <template v-if="record"><strong>{{ formatPoints(record.scores[me.id]!) }} 分</strong><span>平均偏差 {{ average(deviation(me.id), record.settled) }}</span><span>已结算 {{ record.settled }} 题 · 未答 {{ me.unanswered }}</span></template>
        <template v-else-if="room.settings.grid"><strong>{{ me.correct - me.wrong }} 分</strong><span>正确 {{ me.correct }}</span><span>错误 {{ me.wrong }}</span><span>答对时平均 {{ averageCells(me.correct_cells ?? 0, me.correct) }}</span></template>
        <template v-else-if="room.settings.single_life"><span>已通过 {{ me.correct }} 题</span><small>{{ me.eliminated ? '已淘汰' : '存活' }} · 剩余 {{ survivors.length }} 人</small></template>
        <template v-else><span>正确 {{ me.correct }}</span><span>错误 {{ me.wrong }}</span><span>未答 {{ me.unanswered }}</span></template>
      </div>
      <section v-if="room.phase === 'lobby'" class="entry" :class="{ 'setup-entry': editing }">
        <h2>等待开局 · {{ online }}/12 人</h2>
        <template v-if="editing"><div class="setup-columns"><GameRoomSettings v-model="draftSettings" :history="history" /><GameFilterEditor v-model="draftFilters" :face="!history" /></div><div class="actions"><n-button type="primary" :disabled="busy || !!rangeError(draftFilters.start, draftFilters.end)" @click="saveSettings">保存设置</n-button><n-button quaternary @click="editing = false">取消</n-button></div></template>
        <template v-else><GameRoomRules :settings="room.settings" :history="history" />
          <div v-if="host" class="actions"><n-button type="primary" :disabled="busy || online < 2" @click="act('start')">开始对战</n-button><n-button :disabled="busy" @click="editSettings">修改设置</n-button></div>
          <p v-else>等待房主开始对战</p></template>
        <GameFilterSummary v-if="!editing" :filter="activeFilter" />
      </section>
      <template v-else-if="room.phase !== 'finished'">
        <div v-if="room.phase === 'waiting'" class="actions"><p role="status">{{ room.message }}</p><n-button v-if="host" :disabled="busy || online < (solo ? 1 : 2)" @click="act('start')">重新出题</n-button></div>
        <HistoryBoard v-else-if="record?.photo" :key="room.round" :preloading="room.phase === 'loading'" @loaded="act('image_loaded')" :photo="record.photo" :selected="record.my_guess" :correct="record.correct_date"
          :unanswered="!!record.correct_date && !me?.answered" :locked="busy || room.phase !== 'answer' || !me?.playing || me.answered" @choose="guess_date => act('answer', { guess_date })">
          <template #result><span v-if="!solo">{{ closestResult(record, room.players, room.me) }}</span></template>
          <p v-if="!me?.playing" role="status">你将从下一题起参赛</p>
          <p v-else-if="room.phase === 'answer' && me.answered" role="status">已提交，等待揭晓</p>
          <n-button v-if="room.phase === 'reveal' && me?.playing" type="primary" :disabled="busy || me.ready" @click="act('ready')">{{ readyLabel }}</n-button>
          <GameRoomSources v-if="room.source_photo" :group-id="room.source_photo.group_id" :image-id="room.source_photo.image_id" :query="query" />
        </HistoryBoard>
        <GameBoard v-else-if="room.photo" v-slot="{ gridComplete }" :key="room.round" :photo="room.photo" :preloading="room.phase === 'loading'" :cropped="room.settings.cropped" :revealed="room.phase !== 'loading' && room.phase !== 'answer'" @loaded="act('image_loaded')"
          :order="room.grid?.order" :started="gridStarted" :interval="room.settings.grid_seconds" :wrong-choices="room.grid?.wrong_choices" :review-cells="room.grid?.correct_cells" :review-label="solo ? '按住查看作答时的格子' : undefined"
          :locked="busy || room.phase !== 'answer' || !me?.playing || me.answered || !!room.grid?.gave_up" :selected="me?.answered ? room.choice : undefined"
          :correct-id="room.correct_choice" :voided="room.void" :tallies="solo ? null : room.tallies" :answer-name="room.accepted ? room.proposal?.suggested_name : room.answer_name" @choose="choice => act('answer', { choice })">
          <p v-if="!me?.playing" role="status">{{ me?.eliminated ? '已淘汰，正在观战' : '你将从下一题起参赛' }}</p>
          <div v-else-if="room.grid && room.phase === 'answer'" class="grid-answer-help">
            <p role="status">{{ room.grid.gave_up ? (room.settings.single_life ? '本题不再作答，等待揭晓' : '已放弃本题，等待其他玩家') : solo ? '请选择答案' : room.settings.single_life ? '答错即淘汰' : '答对 +1 分，答错 −1 分，可继续抢答' }}</p>
            <n-button v-if="!solo && gridComplete && !room.grid.gave_up" :disabled="busy" @click="act('give_up')">放弃作答</n-button>
          </div>
          <p v-else-if="room.phase === 'answer'" role="status">{{ me.answered ? '已提交，等待揭晓' : '请选择答案' }} · {{ room.players.filter(player => player.answered).length }}/{{ room.players.filter(player => player.playing).length }} 人已答</p>
          <div v-if="room.phase === 'reveal' && me?.playing" class="actions round-actions"><n-button type="primary" :disabled="busy || me.ready" @click="act('ready')">{{ readyLabel }}</n-button><n-button v-if="!solo && room.accepted === null" :disabled="busy" @click="act('draft')">我要反馈</n-button></div>
          <p v-if="room.phase !== 'loading' && room.phase !== 'answer'" role="status">图库答案：{{ room.answer_name }}<template v-if="room.accepted !== null"> · {{ solo ? (me?.answered && room.choice !== room.correct_choice ? '本题已记为存疑' : '反馈已提交') : room.accepted ? (room.void ? '反馈已采纳，本题不计分' : `反馈已采纳，按${voteName}计分`) : '反馈未通过，保留原判' }}</template></p>
          <p v-if="lastRound && room.phase === 'reveal'" role="status">本题结算后结束对战</p>
          <template v-if="room.phase === 'draft'"><p role="status">{{ proposer }} 正在填写反馈，已暂停切题</p>
            <form v-if="room.proposer === room.me" class="feedback" @submit.prevent="act('submit', { suggested_person_id: notFace ? null : person, not_face: notFace, content })">
              <PersonSelect v-model="person" :disabled="notFace" accessible-label="建议人物" placeholder="建议人物（可不选）" />
              <n-checkbox v-model:checked="notFace">不是人脸</n-checkbox><n-input v-model:value="content" type="textarea" :maxlength="1000" placeholder="补充说明（可不填）" :input-props="{ 'aria-label': '补充说明' }" />
              <p>{{ solo ? '反馈仅管理员可见，不影响公开成绩' : '提交后，全房可见，并会送交管理员审核' }}</p><div class="actions"><n-button type="primary" attr-type="submit" :disabled="busy">提交反馈</n-button><n-button :disabled="busy" @click="act('cancel')">取消反馈</n-button></div>
            </form></template>
          <template v-if="room.proposal && !solo"><p class="proposal">{{ proposer }} 提议：{{ voteName }}<template v-if="room.proposal.content"><br />{{ room.proposal.content }}</template></p>
            <p>赞成 {{ room.votes_for }} · 反对 {{ room.votes_against }}</p>
            <div v-if="room.phase === 'vote' && me?.playing && !room.voted" class="actions"><n-button type="primary" :disabled="busy" @click="act('vote', { support: true })">赞成</n-button><n-button :disabled="busy" @click="act('vote', { support: false })">反对</n-button></div>
            <p v-else-if="room.phase === 'vote' && room.voted" role="status">已投票，等待结果</p></template>
          <GameRoomSources v-if="room.source_photo" :group-id="room.source_photo.group_id" :image-id="room.source_photo.image_id" :query="query" :solo="solo" :wrong="me?.answered && room.choice !== room.correct_choice" :face-id="room.revealed_face_id ?? undefined" :choice="room.choice" :draft-key="`${room.match_id}:${room.round}`" :submitted="soloFeedback" />
        </GameBoard>
      </template>
      <div v-if="!solo" class="room-bar"><strong>房间 <span class="code">{{ room.code }}</span></strong>
        <n-button v-if="canInvite" quaternary @click="copyInvite"><Copy :size="15" />复制邀请链接</n-button>
        <span class="spacer" /><router-link v-if="inRound" :to="{ path: gamePath, query: rules }">单人游戏</router-link><n-button quaternary :disabled="busy" @click="act('leave')">离开房间</n-button></div>
      <n-input v-if="showLink && canInvite" readonly :value="invite" :input-props="{ 'aria-label': '邀请链接' }" />
      <SoloGameResult v-if="solo && me && room.phase === 'finished'" :filter="activeFilter" :count="myAnswered" :label="record ? '平均偏差' : '正确率'" :value="record ? record.settled ? (deviation(me.id) / record.settled).toFixed(1) : '—' : myAccuracy" :unit="record?.settled ? '天' : undefined"
        :detail="record ? `累计偏差 ${deviation(me.id)} 天 · 未答 ${me.unanswered} 题` : `答对 ${me.correct} 题 · 未答 ${me.unanswered} 题${room.grid ? ` · 每边 ${room.settings.grid_size} 格 · 答对时平均 ${averageCells(me.correct_cells ?? 0, me.correct)}` : ''}`"
        :breakdown="record ? [{ label: '猜早', count: me.early ?? 0, tone: 'amber' }, { label: '正好', count: myAnswered - (me.early ?? 0) - (me.late ?? 0), tone: 'success' }, { label: '猜晚', count: me.late ?? 0, tone: 'accent' }] : [{ label: '正确', count: me.correct, tone: 'success' }, { label: '错误', count: me.wrong - (me.disputed ?? 0), tone: 'error' }, { label: '存疑', count: me.disputed ?? 0, tone: 'muted' }]" @setup="router.push({ path: gamePath, query: rules })" />
      <RoomPersonalResult v-else-if="me && room.phase === 'finished'" :room="room" :player="me" :rank="showRank ? myRank : null" :tied="tied" />
      <div v-if="solo && inRound" class="actions"><n-button :disabled="busy" @click="act('finish')">结束本局</n-button><router-link :to="otherMode">多人对战</router-link><router-link :to="{ path: '/', query }">返回图库</router-link></div>
      <section v-if="!solo" class="standings"><div class="standings-heading"><h2>{{ room.phase === 'finished' ? '最终排名' : room.phase === 'lobby' ? '房间成员' : '排行榜' }}</h2>
        <n-button v-if="host && room.phase === 'finished'" type="primary" :disabled="busy" @click="act('restart')"><RotateCcw :size="16" aria-hidden="true" />再来一局</n-button></div>
        <p v-if="room.phase === 'finished' && eliminationOver">{{ survivors.length ? `获胜：${survivors[0]!.name}` : '无人存活' }}</p>
        <div class="table-scroll"><table aria-label="房间排行榜"><thead><tr><th v-if="showRank" class="place-col" scope="col">名次</th><th class="player-col" scope="col">玩家</th><template v-if="record"><th v-if="showGuess" scope="col">本题猜测</th><th scope="col">分数</th><th scope="col">平均偏差</th><th scope="col">未答</th></template><th v-else-if="room.settings.single_life" scope="col">通过题数</th><template v-else><th v-if="room.settings.grid" scope="col">分数</th><th scope="col">正确</th><th scope="col">错误</th><th scope="col">{{ room.settings.grid ? '平均格数' : '未答' }}</th></template></tr></thead>
          <tbody><tr v-for="player in ranking" :key="player.id" :class="{ 'own-row': player.id === room.me }"><td v-if="showRank" class="place-col">{{ rank(player) }}</td><th scope="row" class="player-col">{{ player.name }}
            <small>{{ [player.id === room.me ? '你' : '', player.id === room.host ? '房主' : '', player.eliminated ? '已淘汰' : '', !player.online ? '离线' : '', player.ready && room.phase === 'reveal' ? '已准备' : ''].filter(Boolean).join(' · ') }}</small></th>
            <template v-if="record"><td v-if="showGuess && record.photo && record.correct_date"><span>{{ record.guesses?.[player.id] ?? '未答（按居中日期计）' }}</span><small>{{ difference(record.guesses?.[player.id] ?? dayLabel(middleDay(record.photo)), record.correct_date) }}</small></td><td>{{ formatPoints(record.scores[player.id]!) }}</td><td>{{ average(deviation(player.id), record.settled) }}</td><td>{{ player.unanswered }}</td></template>
            <template v-else><td v-if="room.settings.grid">{{ player.correct - player.wrong }}</td><td>{{ player.correct }}</td><template v-if="!room.settings.single_life"><td>{{ player.wrong }}</td><td>{{ room.settings.grid ? averageCells(player.correct_cells ?? 0, player.correct) : player.unanswered }}</td></template></template></tr></tbody></table></div>
        <n-button v-if="host && inRound" :disabled="busy || room.ending" @click="act('finish')">{{ room.ending ? '投票结束后结算' : '结束对战' }}</n-button>
        <GameFilterSummary v-if="room.phase === 'finished'" :filter="activeFilter" />
      </section>
      <GameUpload v-if="me?.eligible && room.phase === 'finished'" :key="room.match_id" v-model:nickname="nickname" :room="room" :token="token" :game-path="gamePath" />
    </template>
    <nav v-if="(!token && !code && !joining) || room?.phase === 'finished'" class="board-links" aria-label="公开排行榜">
      <strong>公开排行榜</strong><div><span v-if="boardUnavailable" role="link" aria-disabled="true" :title="boardUnavailable">当前榜单</span><router-link v-else :to="{ path: gamePath + '/boards/current', query: rules }">当前榜单</router-link><router-link :to="{ path: gamePath + '/boards/filters', query: rules }">当前筛选的榜单</router-link><router-link :to="{ path: gamePath + '/boards/all', query: rules }">全部榜单</router-link></div>
    </nav>
  </main>
  <PostDetail v-if="postKey" :post-key="postKey" :return-path="route.path" />
</template>

<style scoped>
.room-page { width: min(100%, 1440px); margin: 0 auto; padding: 20px 28px 40px; }
header, header a, .room-bar, .round-bar, .actions, .tabs, .my-record { display: flex; align-items: center; gap: 10px; }
header, .round-bar { justify-content: space-between; }
header nav { display: flex; flex-wrap: wrap; gap: 12px; }
.game-heading { flex-wrap: wrap; gap: 0 16px; border-bottom: 1px solid var(--line); }
.board-links, .board-links > div { display: flex; flex-wrap: wrap; align-items: center; gap: 0 16px; }
.board-links { border-top: 1px solid var(--line); padding-top: 8px; margin-top: 24px; }
.board-links a, .board-links span { display: inline-flex; align-items: center; min-height: 44px; }
.board-links span { color: var(--muted); cursor: not-allowed; }
.table-scroll { overflow-x: auto; }
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
@media (max-width: 599px) {
  .setup-entry, .setup-columns, .setup-fields { gap: 10px; }
  .setup-fields > label { grid-template-columns: 5em minmax(0, 1fr); align-items: center; column-gap: 12px; }
  .setup-entry { margin-top: 12px; }
  .setup-entry > button { justify-self: stretch; }
}
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
