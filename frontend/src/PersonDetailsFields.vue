<script setup lang="ts">
import { computed } from "vue";
import { NButton, NInput, NSelect } from "naive-ui";
import { Trash2 } from "@lucide/vue";
import { useLibrary } from "./store";
defineProps<{ disabled?: boolean }>();
const groups = defineModel<(number | string)[]>("groups", { required: true });
const accounts = defineModel<{ platform: string; username: string }[]>(
  "accounts",
  { required: true },
);
const newGroup = defineModel<string>("newGroup", { required: true });
const store = useLibrary();
const options = computed(() => [
  ...store.groups.map((g) => ({ label: g.name, value: g.id })),
  ...groups.value
    .filter((g) => typeof g === "string")
    .map((g) => ({ label: `${g}（新建）`, value: g })),
]);
function addGroup() {
  const value = newGroup.value.trim();
  if (!value) return;
  const key = store.groups.find((g) => g.name === value)?.id || value;
  groups.value = [...new Set([...groups.value, key])];
  newGroup.value = "";
}
</script>
<template>
  <label class="field-label"
    >分组
    <n-select
      v-model:value="groups"
      multiple
      filterable
      :options="options"
      placeholder="选择一个或多个分组"
      :disabled="disabled"
    />
  </label>
  <div class="inline-form">
    <n-input
      v-model:value="newGroup"
      placeholder="新分组名称"
      maxlength="100"
      :disabled="disabled"
      @keydown.enter.prevent="addGroup"
    />
    <n-button :disabled="disabled || !newGroup.trim()" @click="addGroup"
      >新建分组</n-button
    >
  </div>
  <p class="hint">新分组将在保存人物时创建。移除标签仅取消此人的归属。</p>
  <div class="section-heading">
    <h3>关联账号</h3>
    <n-button
      :disabled="disabled"
      @click="accounts.push({ platform: 'instagram', username: '' })"
      >添加账号</n-button
    >
  </div>
  <div v-for="(account, i) in accounts" :key="i" class="inline-form">
    <n-select
      v-model:value="account.platform"
      :aria-label="`账号 ${i + 1} 平台`"
      :disabled="disabled"
      :options="[
        { label: 'Instagram', value: 'instagram' },
        { label: 'X / Twitter', value: 'x' },
      ]"
    />
    <n-input
      v-model:value="account.username"
      :aria-label="`账号 ${i + 1} 用户名`"
      placeholder="用户名"
      maxlength="100"
      :disabled="disabled"
    />
    <n-button
      :aria-label="`移除账号 ${i + 1}`"
      :disabled="disabled"
      @click="accounts.splice(i, 1)"
      ><Trash2 :size="16"
    /></n-button>
  </div>
</template>
