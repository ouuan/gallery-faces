<script setup lang="ts">
import LoadingOverlay from "./LoadingOverlay.vue";
import TrashReview from "./TrashReview.vue";
import { useReviewShortcuts } from "./review-shortcuts";
import { useConfirm } from "./confirm";
const confirm = useConfirm();
import { ref, onMounted, onUnmounted, computed, watch } from "vue";
import { onBeforeRouteLeave, useRoute, useRouter } from "vue-router";
import {
  NButton,
  NDropdown,
  NSelect,
  NCheckbox,
  NRadio,
  NRadioGroup,
  NAlert,
  NInput,
  NModal,
  useMessage,
  type DropdownOption,
} from "naive-ui";
import { api, send, platformLabel, dateLabel } from "./api";
import { useLibrary } from "./store";
import { useLatestRequest } from "./use-latest-request";
import FeedbackPanel from "./FeedbackPanel.vue";
import FaceBoxEditor from "./FaceBoxEditor.vue";
import PersonDetailsFields from "./PersonDetailsFields.vue";
import PersonSelect from "./PersonSelect.vue";
const route = useRoute();
const router = useRouter();
const targetImage = computed(() => {
  const id = typeof route.query.image === "string" ? Number(route.query.image) : NaN;
  return Number.isSafeInteger(id) && id > 0 ? id : null;
});
const reviewStates = ["image", "review", "feedback", "unknown", "no_faces", "failed", "incomplete", "pending", "trash", "all"];
const state = computed({
  get: () => {
    const value = route.query.state === "hidden" ? "trash" : route.query.state;
    if (typeof value === "string" && reviewStates.includes(value)) return value;
    return "review";
  },
  set: (value: string) => {
    void router.replace({ query: { ...route.query, state: value, image: undefined } });
  },
});
const store = useLibrary(),
  message = useMessage(),
  images = ref<any[]>([]),
  selected = ref<number[]>([]),
  error = ref(""),
  loading = ref(false),
  deleting = ref(false),
  acting = ref(false),
  current = ref(0),
  boxPerson = ref<number | null>(null),
  facePeople = ref<Record<number, number | null>>({}),
  box = ref(""),
  savingBox = ref(false),
  savingFaces = ref(false),
  sourceEdit = ref<any>(null);
const newPersonFace = ref<any>(null),
  newPersonName = ref(""),
  newPersonGroups = ref<(number | string)[]>([]),
  newPersonAccounts = ref<{ platform: string; username: string }[]>([]),
  newGroup = ref(""),
  addReference = ref(true),
  creatingPerson = ref(false),
  createError = ref("");
const moreFace = ref<number | null>(null);
const feedbackRefreshVersion = ref(0);
const personDirty = computed(
  () =>
    !!(
      newPersonName.value ||
      newPersonGroups.value.length ||
      newPersonAccounts.value.length ||
      newGroup.value
    ),
);
const dirty = computed(
  () =>
    !!box.value ||
    !!sourceEdit.value ||
    !!(newPersonFace.value && personDirty.value),
);
function openNewPerson(face: any) {
  newPersonFace.value = { ...face };
  newPersonName.value = "";
  newPersonGroups.value = [];
  newPersonAccounts.value = [];
  newGroup.value = "";
  addReference.value = !!face.has_embedding;
  createError.value = "";
}
async function closeNewPerson() {
  if (creatingPerson.value) return;
  if (!personDirty.value || await confirm("有未保存的修改，确定放弃吗？"))
    newPersonFace.value = null;
}
async function createPerson() {
  if (
    creatingPerson.value ||
    !newPersonName.value.trim() ||
    !newPersonFace.value
  )
    return;
  creatingPerson.value = true;
  createError.value = "";
  try {
    const created = await send(
      `/admin/faces/${newPersonFace.value.id}/person`,
      {
        name: newPersonName.value.trim(),
        group_ids: newPersonGroups.value.filter((g) => typeof g === "number"),
        new_groups: [
          ...newPersonGroups.value.filter((g) => typeof g === "string"),
          ...(newGroup.value.trim() ? [newGroup.value.trim()] : []),
        ],
        accounts: newPersonAccounts.value.map((a) => ({
          ...a,
          username: a.username.trim(),
        })),
        revision: newPersonFace.value.revision,
        add_reference: addReference.value,
      },
    );
    facePeople.value[newPersonFace.value.id] = created.id;
    newPersonFace.value = null;
    message.success("人物已创建，当前人脸已确认");
    await store.load();
    await load();
  } catch (e) {
    if (newPersonFace.value) createError.value = (e as Error).message;
    else message.error(`人物已创建，但列表刷新失败：${(e as Error).message}`);
  } finally {
    creatingPerson.value = false;
  }
}
onBeforeRouteLeave(
  async () => !dirty.value || await confirm("有未保存的修改，确定离开吗？"),
);
function unload(e: BeforeUnloadEvent) {
  if (dirty.value) {
    e.preventDefault();
    e.returnValue = "";
  }
}
onMounted(() => window.addEventListener("beforeunload", unload));
onUnmounted(() => window.removeEventListener("beforeunload", unload));
const active = computed(() => images.value[current.value]);
const actionIds = computed(() =>
  selected.value.length ? selected.value : active.value ? [active.value.id] : [],
);
const actionsDisabled = computed(() =>
  !actionIds.value.length || loading.value || deleting.value || acting.value || savingBox.value || savingFaces.value,
);
const navigationDisabled = computed(() =>
  loading.value || deleting.value || acting.value || savingBox.value || savingFaces.value,
);
function moveImage(index: number) {
  if (navigationDisabled.value || index < 0 || index >= images.value.length) return;
  current.value = index;
}
useReviewShortcuts({
  arrowleft: { run: () => moveImage(current.value - 1), enabled: () => current.value > 0 },
  arrowright: { run: () => moveImage(current.value + 1), enabled: () => current.value < images.value.length - 1 },
  c: { run: confirmAll, enabled: () => !actionsDisabled.value && pendingFaces.value.length > 0 },
  d: { run: () => deleteImages(actionIds.value), enabled: () => state.value !== "trash" && !actionsDisabled.value },
}, () => state.value !== "trash" && !!active.value && !navigationDisabled.value && !sourceEdit.value && !newPersonFace.value && moreFace.value === null);
const visibleFaces = computed(() =>
  active.value?.faces.filter((face: any) => !face.ignored) ?? [],
);
const editorImage = computed(() => ({ ...active.value, faces: visibleFaces.value }));
const reviewIssues = computed(() => {
  const image = active.value;
  if (!image || !["review", "all", "image", "hidden"].includes(state.value))
    return [];
  const issues: string[] = [];
  if (image.detection === "pending") issues.push("等待检测");
  if (image.detection === "failed") issues.push("检测失败");
  if (image.incomplete_image_ids?.length)
    issues.push(`来源待补全（图片 ${image.incomplete_image_ids.map((id: number) => "#" + id).join("、")}）`);
  else if (
    image.incomplete_image_ids === undefined && !image.sources.some(
      (source: any) =>
        source.author != null &&
        source.published_at != null &&
        source.url != null,
    )
  )
    issues.push("来源待补全（缺少完整的发布者、发布时间或链接）");
  if (image.detection === "done" && !image.faces.length)
    issues.push("未检测到人脸，需确认是否漏检");
  const unresolved = image.faces.filter(
    (face: any) => !face.locked && !face.ignored,
  );
  const unknown = unresolved.filter((face: any) => face.person_id == null).length;
  const automatic = unresolved.length - unknown;
  if (unknown) issues.push(`未知人物（${unknown} 个人脸）`);
  if (automatic) issues.push(`自动识别结果待确认（${automatic} 个人脸）`);
  if (image.pending_feedback_count) issues.push(`用户反馈（${image.pending_feedback_count} 条待处理）`);
  return issues;
});
watch(
  () => active.value?.id,
  () => {
    box.value = "";
    boxPerson.value = null;
    facePeople.value = {};
    moreFace.value = null;
  },
);
let loadVersion = 0;
const imageRequest = useLatestRequest();
let loadedState: string | null = null;
function syncQuery() {
  if (state.value === "trash" || loading.value || error.value || loadedState !== state.value) return;
  const image = active.value ? String(active.value.id) : undefined;
  if (route.query.state === state.value && route.query.image === image) return;
  void router.replace({ query: { ...route.query, state: state.value, image } });
}
watch(() => active.value?.id, syncQuery);
async function load() {
  const signal = imageRequest.start();
  const version = ++loadVersion;
  const requestedState = state.value;
  const requestedImage = targetImage.value;
  const previousGroup = loadedState === requestedState && requestedImage === active.value?.id
    ? active.value?.group_id : null;
  selected.value = [];
  loading.value = true;
  error.value = "";
  try {
    if (requestedState === "trash") {
      images.value = [];
      loadedState = requestedState;
      return;
    }
    const result = requestedState === "image" && !requestedImage ? [] : await api(
      requestedState === "image"
        ? `/admin/images?state=all&image_id=${requestedImage}`
        : "/admin/images?state=" + requestedState,
      { signal },
    );
    if (version !== loadVersion) return;
    images.value = result;
    selected.value = [];
    const groupIndex = previousGroup == null ? -1 : images.value.findIndex(image => image.group_id === previousGroup);
    const index = groupIndex >= 0 ? groupIndex : images.value.findIndex(image =>
      image.id === requestedImage || image.member_ids?.includes(requestedImage));
    current.value = index >= 0 ? index : Math.min(
      loadedState === requestedState ? current.value : 0,
      Math.max(0, images.value.length - 1),
    );
    loadedState = requestedState;
  } catch (e) {
    if (version === loadVersion) error.value = (e as Error).message;
  } finally {
    if (version === loadVersion) {
      loading.value = false;
      syncQuery();
    }
  }
}
watch([state, targetImage], () => {
  if (loadedState !== state.value || loading.value || error.value ||
      (state.value === "image" && targetImage.value !== (active.value?.id ?? null))) {
    void load();
  } else {
    const index = images.value.findIndex(image =>
      image.id === targetImage.value || image.member_ids?.includes(targetImage.value));
    current.value = index >= 0 ? index : 0;
    syncQuery();
  }
});
onUnmounted(() => { loadVersion++; });
function revealCandidate(event: FocusEvent) {
  const target = event.target as HTMLElement;
  target.closest(".n-radio")?.scrollIntoView({ block: "nearest", inline: "nearest" });
}
function facePerson(face: any): number | null {
  const selection = facePeople.value[face.id];
  return selection === undefined ? face.person_id ?? null : selection;
}
function faceMoreOptions(face: any): DropdownOption[] {
  return [
    { label: "人物", key: "person", props: { role: "menuitem" } },
    {
      label: "参考图",
      key: "reference",
      disabled: facePerson(face) === null || !face.has_embedding,
      props: {
        role: "menuitem",
        "aria-disabled": facePerson(face) === null || !face.has_embedding,
        title: facePerson(face) === null
          ? "请先选择人物"
          : !face.has_embedding ? "此人脸暂无有效特征" : undefined,
      },
    },
  ];
}
async function selectFaceMore(key: string | number, face: any) {
  moreFace.value = null;
  if (savingFaces.value) return;
  if (key === "person") {
    openNewPerson(face);
    return;
  }
  const personId = facePerson(face);
  if (key !== "reference" || personId === null || !face.has_embedding) return;
  savingFaces.value = true;
  try {
    await send(`/admin/people/${personId}/references`, { face_id: face.id });
    message.success("参考图已添加");
    try {
      await store.load();
    } catch (e) {
      message.error(`参考图已添加，但人物列表刷新失败：${(e as Error).message}`);
    }
  } catch (e) {
    message.error((e as Error).message);
  } finally {
    savingFaces.value = false;
  }
}
function faceConfirmed(face: any): boolean {
  const personId = facePerson(face);
  return personId === (face.person_id ?? null) && (!!face.locked || personId === null);
}
const pendingFaces = computed(() =>
  visibleFaces.value.filter((face: any) => !faceConfirmed(face)),
);
async function saveFace(face: any, remove = false) {
  const personId = remove ? null : facePerson(face);
  await send(
    `/admin/faces/${face.id}`,
    {
      revision: face.revision,
      person_id: personId,
      ignored: remove,
      locked: remove || personId !== null,
    },
    "PUT",
  );
  Object.assign(face, { person_id: personId, ignored: remove, locked: remove || personId !== null, revision: face.revision + 1 });
  delete facePeople.value[face.id];
}
async function edit(face: any, remove = false) {
  if (savingFaces.value || (!remove && faceConfirmed(face))) return;
  savingFaces.value = true;
  try {
    await saveFace(face, remove);
    message.success(remove ? "人脸已删除" : "判断已保存");
    await load();
  } catch (e) {
    message.error((e as Error).message);
  } finally {
    savingFaces.value = false;
  }
}
async function confirmAll() {
  if (actionsDisabled.value || !pendingFaces.value.length) return;
  const faces = [...pendingFaces.value];
  savingFaces.value = true;
  try {
    const result = await send("/admin/faces", {
      faces: faces.map(face => ({
        id: face.id,
        revision: face.revision,
        person_id: facePerson(face),
        ignored: false,
        locked: facePerson(face) !== null,
      })),
    }, "PUT");
    for (const face of faces) {
      if (result.saved.includes(face.id)) {
        const personId = facePerson(face);
        Object.assign(face, { person_id: personId, ignored: false, locked: personId !== null, revision: face.revision + 1 });
        delete facePeople.value[face.id];
      }
    }
    const failures = result.failures.map((failure: { id: number; detail: string }) =>
      `人脸 #${failure.id}：${failure.detail}`);
    if (failures.length)
      message.error(`已确认 ${result.saved.length} 个人脸，${failures.length} 个失败。${failures.join("；")}`, { duration: 8000 });
    else {
      message.success(`已确认 ${result.saved.length} 个人脸`);
      await load();
    }
  } catch (e) {
    message.error((e as Error).message);
  } finally {
    savingFaces.value = false;
  }
}
async function action(value: string) {
  if (actionsDisabled.value) return;
  const ids = [...actionIds.value];
  if (
    !await confirm(
      `重新检测${selected.value.length ? "所选" : "当前"} ${ids.length} 组的代表图（${ids.map((id) => "#" + id).join("、")}）？`,
    )
  )
    return;
  acting.value = true;
  try {
    await send("/admin/images/actions", { action: value, ids });
    await load();
  } catch (e) {
    message.error((e as Error).message);
  } finally {
    acting.value = false;
  }
}
async function deleteImages(ids: number[]) {
  if (deleting.value || !ids.length || state.value === "trash") return;
  const targets = [...ids];
  deleting.value = true;
  let recycled = false;
  try {
    const preview = await send("/admin/images/recycle-preview", { ids: targets });
    if (!await confirm(
      `将 ${preview.groups} 组共 ${preview.total} 张图片移入回收站？包含同组的所有重复版本，其中 ${preview.already_trashed} 张已在回收站。所选图片：${targets.map(id => "#" + id).join("、")}。原图和大图将立即清理，缩略图、来源和审核记录保留；恢复需要重新获取原文件。${dirty.value ? "未保存的编辑也会丢弃。" : ""}`,
    )) return;
    const result = await send("/admin/images/actions", {
      action: "delete", ids: targets, scope_token: preview.scope_token,
    });
    recycled = true;
    box.value = "";
    sourceEdit.value = null;
    newPersonFace.value = null;
    boxPerson.value = null;
    facePeople.value = {};
    const affected = new Set<number>(result.ids);
    selected.value = selected.value.filter(id => !affected.has(id));
    images.value = images.value.filter(image => !affected.has(image.id));
    current.value = Math.min(current.value, Math.max(0, images.value.length - 1));
    message.success(`已将 ${result.deleted} 张图片移入回收站`);
    if (result.cleanup_pending) message.warning("部分文件暂未清理，后台将自动重试");
    await load();
    await store.load();
  } catch (e) {
    message.error(`${recycled ? "图片已移入回收站，但列表刷新失败：" : ""}${(e as Error).message}`);
  } finally {
    deleting.value = false;
  }
}

async function addBox() {
  if (savingBox.value || !active.value || !box.value) return;
  savingBox.value = true;
  try {
    await send(`/admin/images/${active.value.id}/faces`, {
      box: box.value.split(",").map(Number),
      person_id: boxPerson.value,
    });
    box.value = "";
    message.success("人脸框已保存");
    await load();
  } catch (e) {
    message.error((e as Error).message);
  } finally {
    savingBox.value = false;
  }
}
function selectFacePerson(faceId: number, personId: number | null) {
  facePeople.value[faceId] = personId;
}
function undoFacePerson(faceId: number) {
  delete facePeople.value[faceId];
}
async function saveSource() {
  try {
    await send(`/admin/posts/${sourceEdit.value.id}`, sourceEdit.value, "PUT");
    sourceEdit.value = null;
    await load();
  } catch (e) {
    message.error((e as Error).message);
  }
}
async function refresh() {
  if ((dirty.value || Object.keys(facePeople.value).length) && !await confirm("有未保存的修改，确定刷新并放弃吗？")) return;
  const previousImageId = active.value?.id;
  box.value = "";
  boxPerson.value = null;
  sourceEdit.value = null;
  newPersonFace.value = null;
  facePeople.value = {};
  await load();
  // A different representative already remounts the panel through its image ID.
  if (active.value?.id === previousImageId) feedbackRefreshVersion.value++;
}
onMounted(load);
</script>
<template>
  <div class="review-toolbar">
    <div class="review-filter">
      <n-select
        aria-label="审核状态"
        :disabled="savingBox || savingFaces || acting || deleting"
        v-model:value="state"
        :options="[
          ...(state === 'image' ? [{ value: 'image', label: '当前重复组' }] : []),
          { value: 'review', label: '全部待审核' },
          { value: 'feedback', label: '用户反馈' },
          { value: 'unknown', label: '未知人物' },
          { value: 'no_faces', label: '无人脸' },
          { value: 'failed', label: '检测失败' },
          { value: 'incomplete', label: '来源待补全' },
          { value: 'pending', label: '等待检测' },
          { value: 'trash', label: '回收站' },
          { value: 'all', label: '全部在库重复组' },
        ]"
      /><span v-if="state !== 'trash'">{{
        selected.length
          ? `已选 ${selected.length} 组`
          : active
            ? `代表图 #${active.id}`
            : "暂无图片"
      }}</span>
    </div>
    <div v-if="state !== 'trash'" class="review-actions">
      <n-button :disabled="navigationDisabled" @click="refresh">刷新</n-button>
      <n-button :disabled="actionsDisabled" @click="selected = selected.length === images.length ? [] : images.map(image => image.id)">
        {{ images.length && selected.length === images.length ? "取消全选" : "全选" }}
      </n-button>
      <n-button :disabled="actionsDisabled" @click="action('redetect')"
        >重新检测</n-button
      >
      <n-button class="stable-loading-button"
        type="error"
        secondary
        :disabled="actionsDisabled"
        :loading="deleting"
        :aria-label="selected.length ? '将所选图片及重复组移入回收站' : '将当前重复组移入回收站'"
        aria-keyshortcuts="d"
        @click="deleteImages(actionIds)"
        >{{ selected.length ? "回收所选重复组" : "移入回收站" }}<kbd class="shortcut-key" aria-hidden="true">D</kbd></n-button
      >
    </div>
  </div>
  <TrashReview v-if="state === 'trash'" />
  <template v-else>
  <n-alert v-if="error" type="error"
    >{{ error }}<n-button @click="load">重试</n-button></n-alert
  >
  <div class="loading-region" :aria-busy="loading">
  <LoadingOverlay :show="loading" label="正在加载审核项目…" />
  <div v-if="!error && !images.length" :style="{ visibility: loading ? 'hidden' : undefined }" class="empty-state">
    <h2>没有需要处理的照片</h2>
    <p>此分类中的项目已处理完毕，也可以切换其他状态</p>
  </div>
  <div v-if="images.length" class="review-workspace">
    <div class="review-strip">
      <div
        v-for="(image, i) in images"
        :key="image.group_id ?? image.id"
        :class="{ active: i === current }"
      >
        <n-checkbox
          :checked="selected.includes(image.id)"
          :aria-label="`选择重复组（代表图 ${image.id}）`"
          @update:checked="
            $event
              ? selected.push(image.id)
              : selected.splice(selected.indexOf(image.id), 1)
          "
        /><button
          @click="moveImage(i)"
          :disabled="navigationDisabled"
          :aria-label="`审核重复组（代表图 ${image.id}，共 ${image.member_count ?? 1} 个版本）`"
          :aria-current="i === current ? 'true' : undefined"
        >
          <img :src="`/api/v1/admin/media/${image.id}?thumbnail=true`" loading="lazy" width="72" height="48" alt="" />#{{ image.id }}
        </button>
      </div>
    </div>
    <div v-if="active" class="review-main">
      <div class="review-heading">
        <h3>代表图 #{{ active.id }} <span class="muted">· 共 {{ active.member_count ?? 1 }} 个版本</span></h3>
        <div class="review-navigation">
          <span class="muted">{{ current + 1 }} / {{ images.length }} 组</span>
          <n-button :disabled="navigationDisabled || current === 0" @click="moveImage(current - 1)" aria-label="上一组" aria-keyshortcuts="ArrowLeft"
            >上一组<kbd class="shortcut-key" aria-hidden="true">←</kbd></n-button
          >
          <n-button
            :disabled="navigationDisabled || current >= images.length - 1"
            @click="moveImage(current + 1)" aria-label="下一组" aria-keyshortcuts="ArrowRight"
            >下一组<kbd class="shortcut-key" aria-hidden="true">→</kbd></n-button
          >
        </div>
      </div>

      <n-alert v-if="reviewIssues.length" type="info" title="待审核问题">
        {{ reviewIssues.join("；") }}
      </n-alert>
      <div class="review-columns">
        <section class="review-preview" aria-label="原图与补框">
          <div
            class="review-stage"
            :style="{ '--review-image-ratio': active.width / active.height }"
          >
            <FaceBoxEditor
              :key="active.id"
              :image="editorImage"
              v-model="box"
              :disabled="savingBox || savingFaces"
            />
          </div>
          <p class="hint">
            直接在图片上拖拽补框，可向任意方向框选；按 Escape 取消
          </p>

          <n-alert v-if="active.error" type="error">{{ active.error }}</n-alert>
          <div class="review-box-controls">
            <PersonSelect
              v-if="box"
              v-model="boxPerson"
              accessible-label="为新框选择人物"
              :disabled="savingBox || savingFaces"
            />
            <div class="inline-form">
              <n-button class="stable-loading-button"
                :disabled="!box || savingBox || savingFaces"
                :loading="savingBox"
                @click="addBox"
                >补框与标签</n-button
              >
              <n-button v-if="box" :disabled="savingBox || savingFaces" @click="box = ''"
                >取消补框</n-button
              >
            </div>
          </div>
        </section>
        <div class="review-details loading-region">
          <FeedbackPanel :key="`${active.id}:${feedbackRefreshVersion}`" :image-id="active.id" :pending-count="active.pending_feedback_count" admin group @changed="load" />
          <section class="review-faces" aria-labelledby="review-faces-title">
            <div class="review-heading">
              <h3 id="review-faces-title">
                人脸审核 <span class="muted">（{{ visibleFaces.length }}）</span>
              </h3>
              <n-button class="stable-loading-button"
                type="primary"
                :disabled="actionsDisabled || !pendingFaces.length"
                :loading="savingFaces"
                aria-label="全部确认"
                aria-keyshortcuts="c"
                title="确认当前图片中所有待确认的人脸，采用当前选择的人物"
                @click="confirmAll"
                >全部确认<kbd class="shortcut-key" aria-hidden="true">C</kbd></n-button
              >
            </div>
            <div
              v-for="face in visibleFaces"
              :key="face.id"
              class="face-review"
            >
              <div class="face-identity">
                <img
                  class="face-crop"
                  :src="`/api/v1/admin/faces/${face.id}/crop`"
                  alt="目标人脸"
                  loading="lazy"
                />
                <div class="face-selection">
                  <h4>人脸 #{{ face.id }}</h4>
                  <PersonSelect
                    :model-value="facePerson(face)"
                    :disabled="savingFaces"
                    :accessible-label="`人脸 #${face.id} 的人物`"
                    @update:model-value="selectFacePerson(face.id, $event)"
                  />
                </div>
              </div>
              <div v-if="face.candidates.length" class="candidate-row">
                <span :id="`similarity-${face.id}`" class="candidate-heading">相似度</span>
                <n-radio-group
                  class="candidate-options"
                  role="radiogroup"
                  :aria-labelledby="`similarity-${face.id}`"
                  :name="`face-candidates-${face.id}`"
                  :value="facePerson(face)"
                  :disabled="savingFaces"
                  @update:value="selectFacePerson(face.id, $event)"
                  @focusin="revealCandidate"
                >
                  <n-radio
                    v-for="candidate in face.candidates"
                    :key="candidate.person_id"
                    :value="candidate.person_id"
                  >
                    {{ store.people.find((p) => p.id === candidate.person_id)?.name }}
                    <span class="candidate-score">{{ candidate.score.toFixed(3) }}</span>
                  </n-radio>
                </n-radio-group>
              </div>
              <div class="button-row">
                <n-button
                  type="primary"
                  secondary
                  :disabled="savingFaces || faceConfirmed(face)"
                  @click="edit(face)"
                  >确认</n-button
                >
                <n-button
                  :disabled="savingFaces || facePerson(face) === (face.person_id ?? null)"
                  @click="undoFacePerson(face.id)"
                  >撤销</n-button
                >
                <n-dropdown
                  trigger="hover"
                  :show="moreFace === face.id"
                  :disabled="savingFaces"
                  :options="faceMoreOptions(face)"
                  :menu-props="() => ({ role: 'menu' })"
                  @update:show="moreFace = $event ? face.id : moreFace === face.id ? null : moreFace"
                  @select="(key: string | number) => selectFaceMore(key, face)"
                  @clickoutside="moreFace = null"
                >
                  <n-button
                    :disabled="savingFaces"
                    aria-haspopup="menu"
                    :aria-expanded="moreFace === face.id"
                    @click="moreFace = face.id"
                    @keydown.down.prevent="moreFace = face.id"
                    @keydown.esc="moreFace = null"
                  >新增</n-button>
                </n-dropdown>
                <n-button type="error" secondary :disabled="savingFaces" @click="edit(face, true)"
                  >删除</n-button
                >
              </div>
            </div>
          </section>
          <section
            class="review-sources"
            aria-labelledby="review-sources-title"
          >
            <h3 id="review-sources-title">组内来源</h3>
            <p v-if="active.incomplete_image_ids?.length" class="hint">
              来源待补全：{{ active.incomplete_image_ids.map((id: number) => "#" + id).join("、") }}
            </p>
            <div
              v-for="source in active.sources"
              :key="source.id"
              class="person-row"
            >
              <span class="grow"
                >{{ platformLabel(source.platform) }} ·
                {{ store.publisherName(source) }} ·
                {{ dateLabel(source.published_at) }}
                <span v-if="source.image_ids?.length" class="hint source-members">图片 {{ source.image_ids.map((id: number) => "#" + id).join("、") }}</span></span
              ><n-button @click="sourceEdit = { ...source }"
                >补全 / 编辑</n-button
              >
            </div>
          </section>
        </div>
      </div>
    </div>
  </div>
  </div>
  <n-modal :show="!!newPersonFace" @update:show="!$event && closeNewPerson()">
    <div
      class="form-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="face-person-title"
    >
      <h2 id="face-person-title">从人脸添加人物</h2>
      <template v-if="newPersonFace">
        <div class="new-person-preview">
          <img
            class="face-crop"
            :src="`/api/v1/admin/faces/${newPersonFace.id}/crop`"
            :alt="`人脸 #${newPersonFace.id}`"
          />
          <p>创建后，人脸 #{{ newPersonFace.id }} 将确认为这位人物</p>
        </div>
        <n-alert v-if="createError" type="error">{{ createError }}</n-alert>
        <form @submit.prevent="createPerson">
          <label class="field-label">
            <span>姓名 <span class="required">必填</span></span>
            <n-input
              v-model:value="newPersonName"
              placeholder="输入新人物姓名"
              maxlength="100"
              autofocus
              :disabled="creatingPerson"
            />
          </label>
          <PersonDetailsFields
            v-model:groups="newPersonGroups"
            v-model:accounts="newPersonAccounts"
            v-model:new-group="newGroup"
            :disabled="creatingPerson"
          />
          <n-checkbox
            v-model:checked="addReference"
            :disabled="creatingPerson || !newPersonFace.has_embedding"
            :aria-disabled="creatingPerson || !newPersonFace.has_embedding"
            >将此人脸作为参考图</n-checkbox
          >
          <p class="hint">
            {{
              newPersonFace.has_embedding
                ? "参考图用于自动匹配其他未知人脸"
                : "此人脸暂无有效特征，可先创建人物，再到人物管理中添加参考图"
            }}
          </p>
          <div class="form-actions">
            <n-button :disabled="creatingPerson" @click="closeNewPerson"
              >取消</n-button
            >
            <n-button class="stable-loading-button"
              type="primary"
              attr-type="submit"
              :loading="creatingPerson"
              :disabled="creatingPerson || !newPersonName.trim()"
              >创建并确认人脸</n-button
            >
          </div>
        </form>
      </template>
    </div>
  </n-modal>
  <n-modal :show="!!sourceEdit" @update:show="!$event && (sourceEdit = null)"
    ><div
      class="form-dialog"
      role="dialog"
      aria-modal="true"
      aria-label="编辑来源"
    >
      <h2>编辑来源</h2>
      <template v-if="sourceEdit">
        <label class="field-label"
          >发布者用户名<n-input v-model:value="sourceEdit.author" /></label
        ><label class="field-label"
          >账号昵称<n-input
            v-model:value="sourceEdit.author_name"
            placeholder="未关联人物时显示" /></label
        ><label class="field-label"
          >时间（含时区）<n-input
            v-model:value="sourceEdit.published_at"
            placeholder="2026-01-01T12:00:00+08:00" /></label
        ><label class="field-label"
          >帖子链接<n-input v-model:value="sourceEdit.url" /></label
        ><label class="field-label"
          >正文<n-input v-model:value="sourceEdit.post_text" type="textarea"
        /></label>
        <div class="form-actions">
          <n-button @click="sourceEdit = null">取消</n-button
          ><n-button type="primary" @click="saveSource">保存来源</n-button>
        </div>
      </template>
    </div></n-modal
  >
  </template>
</template>
<style scoped>
.review-toolbar {
  justify-content: space-between;
  gap: 16px 24px;
}
.review-filter,
.review-actions,
.review-navigation {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 12px;
}
.review-filter > span {
  color: var(--muted);
  font-size: 13px;
}
.review-workspace {
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.review-strip {
  display: flex;
  gap: 8px;
  max-height: none;
  overflow-x: auto;
  padding: 4px 0 8px;
  border-bottom: 1px solid var(--line);
}
.review-strip > div {
  flex-shrink: 0;
  align-items: center;
  gap: 0;
  border-radius: 6px;
}
.review-strip > div.active {
  background: var(--selection);
}
.review-strip :deep(.n-checkbox) {
  padding: 12px 8px;
}
.review-strip button {
  width: 72px;
  border-radius: 4px;
  font-size: 13px;
}
.review-strip img {
  display: block;
  width: 72px;
  height: 48px;
  object-fit: contain;
  margin-bottom: 4px;
}
.review-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.review-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}
.review-navigation > span {
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.review-columns {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-items: start;
  gap: 24px;
}
.review-preview,
.review-details {
  min-width: 0;
}
.review-stage {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 16px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
}
.review-stage :deep(.annotated-image) {
  width: min(100%, calc(52dvh * var(--review-image-ratio)));
  max-width: none;
}
.review-preview > .hint {
  margin-top: 12px;
}
.review-box-controls {
  display: grid;
  gap: 12px;
  margin-top: 16px;
}
.review-box-controls .inline-form,
.review-box-controls .hint {
  margin: 0;
}
.review-box-controls .inline-form {
  flex-wrap: wrap;
}
.review-details {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 24px;
}
.face-review {
  padding: 16px 0;
}
.face-identity {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  align-items: start;
  gap: 12px;
}
.face-identity .face-crop {
  float: none;
  width: 72px;
  height: 72px;
  margin: 0;
  background: var(--panel);
}
.face-selection {
  min-width: 0;
  display: grid;
  gap: 8px;
}
.face-selection h4 {
  margin: 0;
  font-size: 13px;
  font-weight: 550;
}
.face-review .button-row {
  margin-top: 12px;
}
.candidate-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
  min-width: 0;
}
.candidate-heading {
  flex-shrink: 0;
  color: var(--muted);
  font-size: 13px;
}
.candidate-options {
  display: flex;
  flex: 1;
  min-width: 0;
  gap: 16px;
  overflow-x: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--muted) transparent;
  padding: 2px;
}
.candidate-options :deep(.n-radio) {
  flex-shrink: 0;
  align-items: center;
  min-height: 44px;
  margin: 0;
  white-space: nowrap;
}
.candidate-options :deep(.n-radio:has(input:focus-visible)) {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
  border-radius: 4px;
}
.candidate-score {
  margin-left: 4px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}
.review-sources .person-row {
  align-items: start;
  flex-wrap: wrap;
  gap: 12px;
  padding: 16px 0;
}
.source-members {
  display: block;
  overflow-wrap: anywhere;
}
.review-sources .grow {
  flex-basis: 100%;
  overflow-wrap: anywhere;
}
@media (min-width: 1200px) {
  .review-columns {
    grid-template-columns: minmax(0, 1fr) 336px;
  }
  .review-preview {
    position: sticky;
    top: 88px;
  }
}
@media (max-width: 640px) {
  .review-toolbar,
  .review-filter {
    align-items: stretch;
  }
  .review-filter {
    flex: 1 1 100%;
    align-items: center;
    justify-content: space-between;
  }
  .review-workspace {
    gap: 16px;
    margin-top: 16px;
  }
  .review-stage {
    padding: 8px;
  }
}
.new-person-preview {
  display: flex;
  align-items: center;
  gap: 16px;
}
.new-person-preview .face-crop {
  float: none;
  flex-shrink: 0;
  margin: 0;
}
</style>
