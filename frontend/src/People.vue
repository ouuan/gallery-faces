<script setup lang="ts">
import { useConfirm } from "./confirm";
const confirm = useConfirm();
import { ref, computed, watch, onMounted, onUnmounted } from "vue";
import { onBeforeRouteLeave } from "vue-router";
import {
  NButton,
  NInput,
  NSelect,
  NModal,
  NTag,
  NAlert,
  NCheckbox,
  useMessage,
} from "naive-ui";
import { Plus, UserRound } from "@lucide/vue";
import { useLibrary } from "./store";
import PeopleImportDialog from "./PeopleImportDialog.vue";
import PersonAvatar from "./PersonAvatar.vue";
import { useLatestRequest } from "./use-latest-request";
import { useImageDownloads } from "./use-review-images";
import PersonDetailsFields from "./PersonDetailsFields.vue";
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
  selectedGroups = ref<(number | string)[]>([]),
  accounts = ref<{ platform: string; username: string }[]>([]),
  newGroup = ref(""),
  baseline = ref("");
const selectedPeople = ref<number[]>([]),
  importOpen = ref(false),
  importing = ref(false);
const sortedPeople = computed(() => {
  const groupOrder = new Map(
    store.groups.map((group, index) => [group.id, index]),
  );
  return store.people
    .map((person) => ({
      person,
      groupIndex: Math.min(
        store.groups.length,
        ...person.groups.map((group) =>
          groupOrder.get(group.id) ?? store.groups.length,
        ),
      ),
    }))
    .sort((a, b) => a.groupIndex - b.groupIndex)
    .map(({ person }) => person);
});
const importPeople = computed(() =>
  store.people.filter((p) => selectedPeople.value.includes(p.id)),
);
watch(
  () => store.people,
  (people) => {
    selectedPeople.value = selectedPeople.value.filter((id) =>
      people.some((p) => p.id === id),
    );
  },
);
watch(tab, () => {
  selectedPeople.value = [];
});
function selectPerson(personId: number, checked: boolean) {
  selectedPeople.value = checked
    ? [...new Set([...selectedPeople.value, personId])]
    : selectedPeople.value.filter((id) => id !== personId);
}
const references = ref<any[]>([]),
  deletingPerson = ref<number | null>(null),
  upload = ref<any>(null),
  selectedFace = ref<number | null>(null),
  uploading = ref(false),
  removedReferences = ref<number[]>([]),
  groupEdit = ref<any>(null);
type ConfirmedFace = {
  id: number;
  image_id: number;
  has_embedding: number;
  is_reference: number;
};
const confirmedFaces = ref<ConfirmedFace[]>([]),
  selectedReferenceFaces = ref<number[]>([]),
  confirmedLoading = ref(false),
  confirmedError = ref("");
const availableFaces = computed(() =>
  confirmedFaces.value.filter((face) => !face.is_reference),
);
let confirmedRequest = 0;
const faceRequest = useLatestRequest();
watch(editing, value => {
  if (!value) { confirmedRequest++; faceRequest.cancel(); confirmedLoading.value = false; }
});
onUnmounted(() => { confirmedRequest++; });
const { urls: uploadUrls, failed: failedUploads } = useImageDownloads(() =>
  editing.value && upload.value ? [{ id: 0, url: `/api/v1/admin/reference-media/${upload.value.token}.jpg` }] : [],
);
async function loadConfirmedFaces() {
  if (!id.value) return;
  const signal = faceRequest.start();
  const personId = id.value;
  const request = ++confirmedRequest;
  confirmedLoading.value = true;
  confirmedError.value = "";
  try {
    const [faces, refs] = await Promise.all([
      api<ConfirmedFace[]>(`/admin/people/${personId}/confirmed-faces`, { signal }),
      api<any[]>(`/admin/people/${personId}/references`, { signal }),
    ]);
    if (request !== confirmedRequest || id.value !== personId || !editing.value)
      return;
    references.value = refs;
    confirmedFaces.value = faces;
    selectedReferenceFaces.value = selectedReferenceFaces.value.filter(
      (faceId) =>
        faces.some(
          (face) =>
            face.id === faceId && face.has_embedding && !face.is_reference,
        ),
    );
  } catch (e) {
    if (request === confirmedRequest && id.value === personId)
      confirmedError.value = (e as Error).message;
  } finally {
    if (request === confirmedRequest) confirmedLoading.value = false;
  }
}
function toggleReference(faceId: number, checked: boolean) {
  selectedReferenceFaces.value = checked
    ? [...new Set([...selectedReferenceFaces.value, faceId])]
    : selectedReferenceFaces.value.filter((value) => value !== faceId);
}
const formState = () =>
  JSON.stringify([
    name.value,
    selectedGroups.value,
    accounts.value,
    newGroup.value,
    selectedReferenceFaces.value,
    removedReferences.value,
    upload.value?.token,
    selectedFace.value,
  ]);
const dirty = computed(() => editing.value && formState() !== baseline.value);
function open(person?: Person) {
  faceRequest.cancel();
  id.value = person?.id || null;
  name.value = person?.name || "";
  selectedGroups.value = person?.groups.map((g) => g.id) || [];
  accounts.value = person ? JSON.parse(JSON.stringify(person.accounts)) : [];
  newGroup.value = "";
  confirmedRequest++;
  confirmedLoading.value = false;
  references.value = [];
  removedReferences.value = [];
  upload.value = null;
  selectedFace.value = null;
  selectedReferenceFaces.value = [];
  confirmedFaces.value = [];
  confirmedError.value = "";
  baseline.value = formState();
  error.value = "";
  editing.value = true;
  if (id.value) void loadConfirmedFaces();
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
      group_ids: selectedGroups.value.filter(
        (g): g is number => typeof g === "number",
      ),
      new_groups: [
        ...selectedGroups.value.filter(
          (g): g is string => typeof g === "string",
        ),
        ...(newGroup.value.trim() ? [newGroup.value.trim()] : []),
      ],
      reference_face_ids: selectedReferenceFaces.value,
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
  if (dirty.value || uploading.value || saving.value || importing.value) {
    e.preventDefault();
    e.returnValue = "";
  }
}
onBeforeRouteLeave(
  async () =>
    !importing.value &&
    !saving.value &&
    !uploading.value &&
    (!dirty.value || await confirm("有未保存的修改，确定离开吗？")),
);
onMounted(() => window.addEventListener("beforeunload", beforeUnload));
onUnmounted(() => window.removeEventListener("beforeunload", beforeUnload));
</script>
<template>
  <div class="section-heading">
    <div class="tabs">
      <button :class="{ active: tab === 'people' }" @click="tab = 'people'">
        人物</button
      ><button :class="{ active: tab === 'groups' }" @click="tab = 'groups'">
        分组
      </button>
    </div>
    <n-button type="primary" @click="open()"
      ><template #icon><Plus /></template>添加人物</n-button
    >
  </div>
  <template v-if="tab === 'people'"
    ><div v-if="!store.people.length" class="empty-state">
      <UserRound :size="40" />
      <h2>建立你的人物库</h2>
      <p>先添加姓名，再选择参考人脸。有效参考图会用于匹配未知人物</p>
      <n-button @click="open()">添加第一位人物</n-button>
    </div>
    <div v-if="store.people.length" class="people-selection">
      <n-checkbox
        :checked="selectedPeople.length === store.people.length"
        :indeterminate="
          selectedPeople.length > 0 &&
          selectedPeople.length < store.people.length
        "
        @update:checked="
          selectedPeople = $event ? store.people.map((p) => p.id) : []
        "
        >全选</n-checkbox
      >
      <template v-if="selectedPeople.length"
        ><span role="status">已选 {{ selectedPeople.length }} 人</span
        ><n-button type="primary" @click="importOpen = true">导入照片</n-button
        ><n-button @click="selectedPeople = []">清空选择</n-button></template
      >
    </div>
    <div v-for="person in sortedPeople" :key="person.id" class="person-row">
      <n-checkbox
        :checked="selectedPeople.includes(person.id)"
        :aria-label="`选择人物 ${person.name}`"
        @update:checked="selectPerson(person.id, $event)"
      />
      <PersonAvatar
        :reference-id="person.avatar_reference_id"
        :name="person.name"
      />
      <div class="grow">
        <h3>{{ person.name }}</h3>
        <div class="selected-tags">
          <n-tag v-for="g in person.groups" :key="g.id">{{ g.name }}</n-tag>
        </div>
        <p class="muted">
          {{
            person.accounts
              .map((a) => `${platformLabel(a.platform)}: ${a.username}`)
              .join(" · ") || "未关联账号"
          }}
        </p>
      </div>
      <div>
        <p>{{ person.reference_count }} 张参考图</p>
        <p v-if="!person.reference_count" class="hint">尚不能自动匹配</p>
      </div>
      <n-button @click="open(person)">编辑</n-button
      ><n-button
        type="error"
        secondary
        :aria-label="`删除人物 ${person.name}`"
        :loading="deletingPerson === person.id"
        :disabled="deletingPerson !== null"
        @click="removePerson(person)"
        >删除</n-button
      >
    </div></template
  ><template v-else
    ><p v-if="!store.groups.length" class="empty-state">
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
    </div></template
  >
  <PeopleImportDialog
    v-if="importOpen"
    :people="importPeople"
    @close="importOpen = false"
    @busy="importing = $event"
  />
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
          v-model:groups="selectedGroups"
          v-model:accounts="accounts"
          v-model:new-group="newGroup"
          :disabled="saving"
        />
        <section aria-labelledby="references-title">
          <h3 id="references-title">参考图</h3>
          <p class="hint">选择、删除或上传参考图，保存人物后生效</p>
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
          <p v-else-if="!confirmedLoading && !confirmedError" class="hint">
            暂无参考图，可选择已确认人脸或上传图片
          </p>
          <template v-if="id">
            <div class="section-heading">
              <h3 id="confirmed-faces-title">选择已确认人脸</h3>
              <n-button
                :disabled="saving || confirmedLoading"
                @click="loadConfirmedFaces"
                >刷新人脸</n-button
              >
            </div>
            <p class="hint">可多选；已有参考图可在上方删除</p>
            <n-alert v-if="confirmedError" type="error"
              >{{ confirmedError
              }}<n-button @click="loadConfirmedFaces">重试</n-button></n-alert
            >
            <p v-else-if="confirmedLoading" role="status">
              正在加载已确认人脸…
            </p>
            <p v-else-if="!availableFaces.length" class="hint">
              暂无可添加的已确认人脸。可到识别审核中确认更多人脸
            </p>
            <div v-else class="confirmed-face-grid">
              <label
                v-for="face in availableFaces"
                :key="face.id"
                class="confirmed-face"
              >
                <img
                  :src="`/api/v1/admin/faces/${face.id}/crop`"
                  :alt="`人脸 #${face.id}`"
                  loading="lazy"
                />
                <n-checkbox
                  :checked="
                    !!face.is_reference ||
                    selectedReferenceFaces.includes(face.id)
                  "
                  :disabled="
                    saving || !!face.is_reference || !face.has_embedding
                  "
                  :aria-disabled="
                    saving || !!face.is_reference || !face.has_embedding
                  "
                  :aria-label="`人脸 #${face.id} 设为参考图`"
                  @update:checked="toggleReference(face.id, $event)"
                  >#{{ face.id }}</n-checkbox
                >
                <span class="hint">{{
                  face.is_reference
                    ? "已是参考图"
                    : !face.has_embedding
                      ? "暂无有效特征"
                      : `图片 #${face.image_id}`
                }}</span>
              </label>
            </div>
            <p v-if="selectedReferenceFaces.length" class="hint">
              将添加 {{ selectedReferenceFaces.length }} 张参考图
            </p>
          </template>
          <label class="field-label"
            >上传参考图片<input
              type="file"
              accept="image/*"
              :disabled="saving || uploading"
              @change="uploadFile"
          /></label>
          <p v-if="uploading" role="status">正在上传并检测人脸…</p>
          <div v-if="upload">
            <p v-if="failedUploads.has(0)" role="status">图片加载失败</p>
            <p v-else-if="!uploadUrls.has(0)" role="status">正在加载图片…</p>
            <div class="annotated-image">
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
          ><n-button
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
      v-if="groupEdit"
      class="form-dialog"
      role="dialog"
      aria-modal="true"
      aria-label="编辑分组"
    >
      <h2>编辑分组</h2>
      <label class="field-label"
        >名称<n-input v-model:value="groupEdit.name" /></label
      ><label class="field-label"
        >成员<n-select
          v-model:value="groupEdit.person_ids"
          multiple
          filterable
          :options="store.people.map((p) => ({ label: p.name, value: p.id }))"
      /></label>
      <div class="form-actions">
        <n-button @click="groupEdit = null">取消</n-button
        ><n-button type="primary" @click="saveGroup">保存分组</n-button>
      </div>
    </div></n-modal
  >
</template>

<style scoped>
.people-selection {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  margin: 16px 0;
}
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

.confirmed-face-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
  gap: 16px;
  max-height: 320px;
  overflow-y: auto;
  padding: 4px;
}
.confirmed-face {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.confirmed-face img {
  width: 100%;
  height: 96px;
  object-fit: contain;
  background: var(--bg);
}
</style>
