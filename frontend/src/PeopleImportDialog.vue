<script setup lang="ts">
import LocalDateTime from "./LocalDateTime.vue";
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { NAlert, NButton, NModal } from "naive-ui";
import {
  send,
  platformLabel,
  type Person,
  type ImportResult,
} from "./api";
import DateRangeHint from "./DateRangeHint.vue";
const props = defineProps<{ people: Person[] }>();
const emit = defineEmits<{ close: []; busy: [value: boolean] }>();
const router = useRouter();
const start = ref(""),
  end = ref(""),
  busy = ref(false),
  error = ref("");
const results = ref<ImportResult[] | null>(null);
const accounts = computed(() => {
  const unique = new Map<string, { url: string; label: string }>();
  for (const person of props.people)
    for (const account of person.accounts) {
      const username = account.username.trim().toLowerCase();
      const url = `https://${account.platform === "x" ? "x.com" : "instagram.com"}/${username}`;
      unique.set(url, {
        url,
        label: `${platformLabel(account.platform)}: ${username}`,
      });
    }
  return [...unique.values()];
});
const skipped = computed(() =>
  props.people
    .filter((p) => !p.accounts.length)
    .map((p) => p.name)
    .join("、"),
);
const invalidRange = computed(
  () => !!start.value && !!end.value && Date.parse(start.value) >= Date.parse(end.value),
);
function close() {
  if (!busy.value) emit("close");
}
async function submit() {
  if (
    busy.value ||
    invalidRange.value ||
    !accounts.value.length ||
    results.value
  )
    return;
  busy.value = true;
  emit("busy", true);
  error.value = "";
  try {
    results.value = await send("/admin/import", {
      urls: accounts.value.map((a) => a.url),
      start: start.value,
      end: end.value,
    });
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
    emit("busy", false);
  }
}
function viewTasks() {
  close();
  void router.push("/admin/import");
}
</script>
<template>
  <n-modal :show="true" @update:show="!$event && close()">
    <div
      class="form-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="people-import-title"
    >
      <h2 id="people-import-title">导入照片</h2>
      <p class="import-people">
        已选 {{ people.length }} 人：{{ people.map((p) => p.name).join("、") }}
      </p>
      <p class="hint">
        导入关联账号发布的照片，照片中的人物将由识别和审核确定
      </p>
      <n-alert v-if="skipped" type="warning"
        >以下人物未关联账号，将跳过：{{ skipped }}</n-alert
      >
      <ul v-if="accounts.length" class="account-list">
        <li v-for="account in accounts" :key="account.url">
          {{ account.label }}
        </li>
      </ul>
      <template v-if="results !== null">
        <p role="status">
          已创建
          {{ results.filter((r) => r.status === "queued").length }} 个任务，复用
          {{ results.filter((r) => r.status === "duplicate").length }} 个任务
        </p>
        <div
          v-for="result in results"
          :key="result.value"
          class="import-result"
        >
          <span>{{
            accounts.find((a) => a.url === result.value)?.label || result.value
          }}</span>
          <strong
            >{{
              result.status === "queued"
                ? "已加入队列"
                : result.status === "duplicate"
                  ? "已有相同范围任务"
                  : "账号链接无效"
            }}<template v-if="result.task_id">
              #{{ result.task_id }}</template
            ></strong
          >
        </div>
        <div class="form-actions">
          <n-button @click="close">关闭</n-button
          ><n-button type="primary" @click="viewTasks">查看导入任务</n-button>
        </div>
      </template>
      <form v-else @submit.prevent="submit">
        <n-alert v-if="error" type="error">{{ error }}</n-alert>
        <div class="import-dates">
          <label class="field-label"
            >开始时间<LocalDateTime aria-label="开始时间" v-model="start" :disabled="busy" /></label>
          <label class="field-label"
            >结束时间（不含）<LocalDateTime aria-label="结束时间（不含）" v-model="end" :disabled="busy" /></label>
        </div>
        <DateRangeHint :start="start" :end="end" />
        <p class="hint">留空表示不限对应日期</p>
        <n-alert v-if="invalidRange" type="error"
          >结束时间必须晚于开始时间</n-alert
        >
        <div class="form-actions">
          <n-button :disabled="busy" @click="close">取消</n-button
          ><n-button class="stable-loading-button"
            type="primary"
            attr-type="submit"
            :loading="busy"
            :disabled="busy || invalidRange || !accounts.length"
            >创建导入任务</n-button
          >
        </div>
      </form>
    </div>
  </n-modal>
</template>
<style scoped>
.import-people,
.account-list {
  overflow-wrap: anywhere;
}
.account-list {
  max-height: 180px;
  overflow-y: auto;
  padding-left: 24px;
}
.import-dates {
  display: flex;
  gap: 16px;
}
.import-dates > label {
  flex: 1;
  min-width: 0;
}
.import-result {
  flex-wrap: wrap;
}
@media (max-width: 640px) {
  .import-dates {
    flex-direction: column;
    gap: 0;
  }
}
</style>
