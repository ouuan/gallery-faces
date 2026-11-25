<script setup lang="ts">
import { computed } from "vue";
import { NButton, NInput, NSelect } from "naive-ui";
import { Trash2 } from "@lucide/vue";
import { useLibrary } from "./store";
import { emptyGroup, type SelectedGroup } from "./person-groups";
defineProps<{ disabled?: boolean }>();
const groups = defineModel<SelectedGroup[]>("groups", { required: true });
const nameJa = defineModel<string>("nameJa", { required: true });
const accounts = defineModel<{ platform: string; username: string }[]>(
  "accounts",
  { required: true },
);
const newGroup = defineModel<ReturnType<typeof emptyGroup>>("newGroup", { required: true });
const store = useLibrary();
const options = computed(() => [
  ...store.groups.map((g) => ({ label: g.name, value: g.id })),
  ...groups.value
    .filter((group) => typeof group !== "number")
    .map((group) => ({ label: `${group.name}（新建）`, value: group.name })),
]);
const selection = computed({
  get: () => groups.value.map(group => typeof group === "number" ? group : group.name),
  set: (values: (number | string)[]) => {
    groups.value = values.map(value => typeof value === "number" ? value :
      groups.value.find(group => typeof group !== "number" && group.name === value)!);
  },
});
function addGroup() {
  const value = newGroup.value.name.trim();
  if (!value) return;
  const key = store.groups.find((g) => g.name === value)?.id || value;
  if (!selection.value.includes(key)) {
    groups.value = [...groups.value, typeof key === "number" ? key : { ...newGroup.value, name: value }];
  }
  newGroup.value = emptyGroup();
}
</script>
<template>
  <label class="field-label">日语名称（可选）<n-input v-model:value="nameJa" maxlength="100" placeholder="未填写时使用原名" :disabled="disabled" /></label>
  <label class="field-label"
    >分组
    <n-select
      :to="false"
      :max-tag-count="2"
      v-model:value="selection"
      multiple
      filterable
      :options="options"
      placeholder="选择一个或多个分组"
      :disabled="disabled"
    />
  </label>
    <n-input
      v-model:value="newGroup.name"
      placeholder="新分组名称"
      maxlength="100"
      :disabled="disabled"
      @keydown.enter.prevent="addGroup"
    />
  <div class="inline-form">
    <n-input v-model:value="newGroup.name_ja" placeholder="新分组日语名称（可选）" maxlength="100" :disabled="disabled" @keydown.enter.prevent="addGroup" />
    <n-button :disabled="disabled || !newGroup.name.trim()" @click="addGroup"
      >新建分组</n-button
    >
  </div>
  <p class="hint">新分组将在保存人物时创建。移除标签仅取消此人的归属</p>
  <div class="section-heading">
    <h3>关联账号</h3>
    <n-button
      :disabled="disabled"
      @click="accounts.push({ platform: 'x', username: '' })"
      >添加账号</n-button
    >
  </div>
  <div v-for="(account, i) in accounts" :key="i" class="inline-form">
    <n-select
      :to="false"
      v-model:value="account.platform"
      :aria-label="`账号 ${i + 1} 平台`"
      :disabled="disabled"
      :options="[
        { label: 'X / Twitter', value: 'x' },
        { label: 'Instagram', value: 'instagram' },
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
