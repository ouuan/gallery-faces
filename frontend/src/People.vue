<script setup lang="ts">
import LoadingOverlay from "./LoadingOverlay.vue";
import { useConfirm } from "./confirm";
const confirm = useConfirm();
import { ref, computed, watch, onMounted, onUnmounted } from "vue";
import { onBeforeRouteLeave } from "vue-router";
import {
  NButton,
  NCollapse,
  NCollapseItem,
  NInput,
  NSelect,
  NModal,
  NTag,
  NTabs,
  NTabPane,
  NAlert,
  useMessage,
} from "naive-ui";
import { Plus, UserRound } from "@lucide/vue";
import { useLibrary } from "./store";
import PersonAvatar from "./PersonAvatar.vue";
import { useLatestRequest } from "./use-latest-request";
import { useImageDownloads } from "./use-review-images";
import PersonDetailsFields from "./PersonDetailsFields.vue";
import { emptyGroup, groupPeople, personGroupPayload, type SelectedGroup } from "./person-groups";
import type { components } from "./schema";
import { api, send, platformLabel, type Person } from "./api";
const store = useLibrary(),
  message = useMessage(),
  tab = ref("people"),
  editing = ref(false),
  saving = ref(false),
  error = ref(""),
  id = ref<number | null>(null),
  name = ref(""),
  nameJa = ref(""),
  selectedGroups = ref<SelectedGroup[]>([]),
  accounts = ref<{ platform: string; username: string }[]>([]),
  newGroup = ref(emptyGroup()),
  baseline = ref("");
const peopleGroups = computed(() => groupPeople(store.people, store.groups));
const expandedGroups = ref<number[]>([]);
const references = ref<{ id: number }[]>([]),
  referencesLoading = ref(false),
  referencesError = ref(""),
  deletingPerson = ref<number | null>(null),
  upload = ref<any>(null),
  selectedFace = ref<number | null>(null),
  uploading = ref(false),
  removedReferences = ref<number[]>([]),
  groupEdit = ref<any>(null);
const { urls: uploadUrls, failed: failedUploads } = useImageDownloads(() =>
  editing.value && upload.value ? [{ id: 0, url: `/api/v1/admin/reference-media/${upload.value.token}.jpg` }] : [],
);
const referencesRequest = useLatestRequest();
watch(editing, (open) => { if (!open) referencesRequest.cancel(); });
async function loadReferences() {
  if (!id.value) return;
  const signal = referencesRequest.start();
  referencesLoading.value = true;
  referencesError.value = "";
  try {
    const items = await api<{ id: number }[]>(`/admin/people/${id.value}/references`, { signal });
    if (!signal.aborted) references.value = items;
  } catch (e) {
    if (!signal.aborted) referencesError.value = (e as Error).message;
  } finally {
    if (!signal.aborted) referencesLoading.value = false;
  }
}
const formState = () =>
  JSON.stringify([
    name.value,
    nameJa.value,
    selectedGroups.value,
    accounts.value,
    newGroup.value,
    removedReferences.value,
    upload.value?.token,
    selectedFace.value,
  ]);
const dirty = computed(() => editing.value && formState() !== baseline.value);
function open(person?: Person) {
  referencesRequest.cancel();
  referencesLoading.value = false;
  referencesError.value = "";
  id.value = person?.id || null;
  name.value = person?.name || "";
  nameJa.value = person?.name_ja || "";
  selectedGroups.value = person?.groups.map((g) => g.id) || [];
  accounts.value = person ? JSON.parse(JSON.stringify(person.accounts)) : [];
  newGroup.value = emptyGroup();
  references.value = [];
  removedReferences.value = [];
  upload.value = null;
  selectedFace.value = null;
  baseline.value = formState();
  error.value = "";
  editing.value = true;
  if (id.value) void loadReferences();
}
async function close() {
  if (saving.value || uploading.value) return;
  if (!dirty.value || await confirm("有未保存的修改，确定放弃吗？"))
    editing.value = false;
}
async function save() {
  if (saving.value || uploading.value) return;
  if (upload.value && selectedFace.value === null) return;
  saving.value = true;
  error.value = "";
  try {
    const body: components["schemas"]["PersonInput"] = {
      name: name.value,
      name_ja: nameJa.value,
      ...personGroupPayload(selectedGroups.value, newGroup.value),
      removed_reference_ids: removedReferences.value,
      uploaded_references:
        upload.value && selectedFace.value !== null
          ? [{ token: upload.value.token, index: selectedFace.value }]
          : [],
      accounts: accounts.value.map((a) => ({
        platform: a.platform as "instagram" | "x",
        username: a.username.trim(),
      })),
    };
    await send(
      "/admin/people" + (id.value ? `/${id.value}` : ""),
      body,
      id.value ? "PUT" : "POST",
    );
    editing.value = false;
    await store.load();
    message.success("人物已保存");
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    saving.value = false;
  }
}
async function uploadFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file || saving.value || uploading.value) return;
  const data = new FormData();
  data.append("file", file);
  uploading.value = true;
  try {
    const result = await api("/admin/reference-upload", {
      method: "POST",
      body: data,
    });
    upload.value = result;
    selectedFace.value = result.faces.length === 1 ? 0 : null;
  } catch (e) {
    message.error((e as Error).message);
  } finally {
    uploading.value = false;
    input.value = "";
  }
}
function toggleRemoval(refId: number) {
  removedReferences.value = removedReferences.value.includes(refId)
    ? removedReferences.value.filter((value) => value !== refId)
    : [...removedReferences.value, refId];
}
async function saveGroup() {
  try {
    await send(`/admin/groups/${groupEdit.value.id}`, groupEdit.value, "PUT");
    groupEdit.value = null;
    await store.load();
  } catch (e) {
    message.error((e as Error).message);
  }
}
async function removeGroup(group: any) {
  if (!await confirm(`删除分组“${group.name}”？人物将保留。`)) return;
  await api(`/admin/groups/${group.id}`, { method: "DELETE" });
  await store.load();
}
async function removePerson(person: Person) {
  if (deletingPerson.value !== null) return;
  if (
    !await confirm(
      `删除人物“${person.name}”？照片会保留，关联人脸将恢复为未知；该人物的参考图、账号和分组关联将被移除。此操作不可撤销。`,
    )
  )
    return;
  deletingPerson.value = person.id;
  let deleted = false;
  try {
    await api(`/admin/people/${person.id}`, { method: "DELETE" });
    deleted = true;
    store.people = store.people.filter((p) => p.id !== person.id);
    message.success("人物已删除，照片已保留");
    await store.load();
  } catch (e) {
    message.error(
      `${deleted ? "人物已删除，但列表刷新失败：" : ""}${(e as Error).message}`,
    );
  } finally {
    deletingPerson.value = null;
  }
}
function beforeUnload(e: BeforeUnloadEvent) {
  if (dirty.value || uploading.value || saving.value) {
    e.preventDefault();
    e.returnValue = "";
  }
}
onBeforeRouteLeave(
  async () =>
    !saving.value &&
    !uploading.value &&
    (!dirty.value || await confirm("有未保存的修改，确定离开吗？")),
);
onMounted(() => window.addEventListener("beforeunload", beforeUnload));
onUnmounted(() => window.removeEventListener("beforeunload", beforeUnload));
</script>
<template>
  <n-tabs v-model:value="tab" type="line">
    <template #suffix>
      <n-button type="primary" @click="open()"><template #icon><Plus /></template>添加人物</n-button>
    </template>
    <n-tab-pane name="people">
      <template #tab><button type="button" class="people-tab" :aria-pressed="tab === 'people'">人物</button></template>
      <div v-if="!store.people.length" class="empty-state">
      <UserRound :size="40" />
      <h2>建立你的人物库</h2>
      <p>先添加姓名，再选择参考人脸。有效参考图会用于匹配未知人物</p>
      <n-button @click="open()">添加第一位人物</n-button>
    </div>
    <n-collapse v-else v-model:expanded-names="expandedGroups" display-directive="if">
      <n-collapse-item v-for="group in peopleGroups" :key="group.id" :name="group.id">
        <template #header="{ collapsed }">
          <h2 class="grow">
            <button type="button" class="group-toggle" :aria-expanded="!collapsed"
              :aria-controls="collapsed ? undefined : `people-group-${group.id}`">
              <span class="grow">{{ group.name }}</span>
              <span class="group-count">{{ group.members.length }} 人</span>
            </button>
          </h2>
        </template>
        <div :id="`people-group-${group.id}`">
          <div v-for="person in group.members" :key="person.id" class="person-row">
            <PersonAvatar :reference-id="person.avatar_reference_id" :name="person.name" />
            <div class="grow">
              <h3>{{ person.name }}</h3>
              <div class="selected-tags">
                <n-tag v-for="g in person.groups" :key="g.id">{{ g.name }}</n-tag>
              </div>
              <p class="muted">
                {{ person.accounts.map((a) => `${platformLabel(a.platform)}: ${a.username}`).join(" · ") || "未关联账号" }}
              </p>
            </div>
            <div>
              <p>{{ person.photo_group_count }} 张图库照片</p>
              <p>{{ person.reference_count }} 张参考图</p>
              <p v-if="!person.reference_count" class="hint">尚不能自动匹配</p>
            </div>
            <n-button @click="open(person)">编辑</n-button>
            <n-button class="stable-loading-button" type="error" secondary
              :aria-label="`删除人物 ${person.name}`" :loading="deletingPerson === person.id"
              :disabled="deletingPerson !== null" @click="removePerson(person)">删除</n-button>
          </div>
        </div>
      </n-collapse-item>
    </n-collapse>
    </n-tab-pane>
    <n-tab-pane name="groups">
      <template #tab><button type="button" class="people-tab" :aria-pressed="tab === 'groups'">分组</button></template>
      <p v-if="!store.groups.length" class="empty-state">
      暂无分组。可在人物编辑中直接新建
    </p>
    <div v-for="g in store.groups" :key="g.id" class="person-row">
      <strong class="grow">{{ g.name }}</strong
      ><span
        >{{
          store.people.filter((p) => p.groups.some((x) => x.id === g.id)).length
        }}
        人</span
      ><n-button
        @click="
          groupEdit = {
            ...g,
            person_ids: store.people
              .filter((p) => p.groups.some((x) => x.id === g.id))
              .map((p) => p.id),
          }
        "
        >编辑成员</n-button
      ><n-button @click="removeGroup(g)">删除</n-button>
    </div>
    </n-tab-pane>
  </n-tabs>
  <n-modal :show="editing" @update:show="!$event && close()"
    ><div
      class="form-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="person-title"
    >
      <h2 id="person-title">{{ id ? "编辑人物" : "添加人物" }}</h2>
      <n-alert v-if="error" type="error">{{ error }}</n-alert>
      <form @submit.prevent="save">
        <label class="field-label"
          >姓名 <span class="required">必填</span
          ><n-input
            v-model:value="name"
            placeholder="输入主姓名"
            maxlength="100"
            :disabled="saving"
            autofocus
        /></label>
        <PersonDetailsFields
          v-model:name-ja="nameJa"
          v-model:groups="selectedGroups"
          v-model:accounts="accounts"
          v-model:new-group="newGroup"
          :disabled="saving"
        />
        <section aria-labelledby="references-title">
          <h3 id="references-title">参考图</h3>
          <p class="hint">上传或删除参考图后，保存人物即可生效</p>
          <div v-if="references.length" class="reference-grid">
            <div
              v-for="r in references"
              :key="r.id"
              :class="{ 'pending-removal': removedReferences.includes(r.id) }"
            >
              <img
                :src="`/api/v1/admin/references/${r.id}/crop`"
                :alt="`参考图 #${r.id}`"
                loading="lazy"
              />
              <n-button
                :disabled="saving"
                :aria-label="`${removedReferences.includes(r.id) ? '撤销删除' : '删除参考图'} #${r.id}`"
                @click="toggleRemoval(r.id)"
                >{{
                  removedReferences.includes(r.id) ? "撤销删除" : "删除参考图"
                }}</n-button
              >
            </div>
          </div>
          <n-alert v-else-if="referencesError" type="error">
            {{ referencesError }} <n-button @click="loadReferences">重试</n-button>
          </n-alert>
          <p v-else class="hint" role="status">{{ referencesLoading ? '正在加载参考图…' : '暂无参考图' }}</p>
          <div class="loading-region" :aria-busy="uploading">
          <LoadingOverlay :show="uploading" label="正在上传并检测人脸…" />
          <label class="field-label"
            >上传参考图片<input
              type="file"
              accept="image/*"
              :disabled="saving || uploading"
              @change="uploadFile"
          /></label>
          </div>
          <div v-if="upload">
            <div class="annotated-image" :style="{ aspectRatio: `${upload.width} / ${upload.height}` }" :aria-busy="!uploadUrls.has(0) && !failedUploads.has(0)">
              <LoadingOverlay :show="failedUploads.has(0) || !uploadUrls.has(0)" center :error="failedUploads.has(0)" :label="failedUploads.has(0) ? '图片加载失败' : '正在加载图片…'" />
              <img
                v-if="uploadUrls.has(0)"
                :src="uploadUrls.get(0)"
                alt="上传的参考图"
                @error="failedUploads.add(0)"
              /><button
                v-for="f in uploadUrls.has(0) ? upload.faces : []"
                :key="f.index"
                type="button"
                :disabled="saving || uploading"
                :aria-pressed="selectedFace === f.index"
                class="face-box reference-target"
                :class="{ chosen: selectedFace === f.index }"
                :aria-label="`选择人脸 ${f.index + 1}`"
                :style="{
                  left: (f.box[0] / upload.width) * 100 + '%',
                  top: (f.box[1] / upload.height) * 100 + '%',
                  width: (f.box[2] / upload.width) * 100 + '%',
                  height: (f.box[3] / upload.height) * 100 + '%',
                }"
                @click="selectedFace = f.index"
              >
                {{ f.index + 1 }}
              </button>
            </div>
            <p>选择要作为参考图的人脸</p>
            <n-select
              :to="false"
              v-model:value="selectedFace"
              :disabled="saving || uploading"
              :options="
                upload.faces.map((f: any) => ({
                  value: f.index,
                  label: `人脸 ${f.index + 1}`,
                }))
              "
              placeholder="多人图片必须明确选择"
            />
          </div>
          <n-button
            v-if="upload"
            :disabled="saving || uploading"
            @click="
              upload = null;
              selectedFace = null;
            "
            >移除待上传参考图</n-button
          >
        </section>
        <div class="form-actions">
          <n-button :disabled="saving || uploading" @click="close"
            >取消</n-button
          ><n-button class="stable-loading-button"
            type="primary"
            attr-type="submit"
            :loading="saving"
            :disabled="uploading || (!!upload && selectedFace === null)"
            >保存人物</n-button
          >
        </div>
      </form>
    </div></n-modal
  >
  <n-modal :show="!!groupEdit" @update:show="!$event && (groupEdit = null)"
    ><div
      class="form-dialog"
      role="dialog"
      aria-modal="true"
      aria-label="编辑分组"
    >
      <h2>编辑分组</h2>
      <template v-if="groupEdit">
        <label class="field-label"
          >名称<n-input v-model:value="groupEdit.name" /></label
        >
        <label class="field-label">日语名称（可选）<n-input v-model:value="groupEdit.name_ja" maxlength="100" placeholder="未填写时使用原名" /></label>
        <label class="field-label"
          >成员<n-select
            :to="false"
            :max-tag-count="2"
            v-model:value="groupEdit.person_ids"
            multiple
            filterable
            :options="store.people.map((p) => ({ label: p.name, value: p.id }))"
        /></label>
        <div class="form-actions">
          <n-button @click="groupEdit = null">取消</n-button
          ><n-button type="primary" @click="saveGroup">保存分组</n-button>
        </div>
      </template>
    </div></n-modal
  >
</template>

<style scoped>
.people-tab { border: 0; padding: 0; color: inherit; background: none; font: inherit; }
.group-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-height: 44px;
  padding: 8px;
  border: 0;
  background: transparent;
  color: inherit;
  font-size: 16px;
  font-weight: 600;
  text-align: left;
  overflow-wrap: anywhere;
}
.group-toggle:hover { background: var(--bg); }
.group-count { color: var(--muted); font-size: 13px; font-weight: 400; }

@media (max-width: 640px) {
  .person-row {
    flex-wrap: wrap;
    gap: 12px;
  }
  .person-row .grow {
    flex-basis: calc(100% - 110px);
  }
  .person-row .grow p {
    overflow-wrap: anywhere;
  }
}

.pending-removal img {
  opacity: 0.4;
}

</style>
