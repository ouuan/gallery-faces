<script setup lang="ts">
import { ref, watch } from "vue";
import { UserRound } from "@lucide/vue";
const props = defineProps<{ referenceId: number | null; name: string }>();
const failed = ref(false);
watch(
  () => props.referenceId,
  () => {
    failed.value = false;
  },
);
</script>
<template>
  <img
    v-if="referenceId && !failed"
    class="avatar large"
    :src="`/api/v1/admin/references/${referenceId}/crop`"
    :alt="`${name}的参考人脸`"
    loading="lazy"
    @error="failed = true"
  />
  <span
    v-else
    class="avatar large"
    role="img"
    :aria-label="failed ? '参考图无法加载' : '暂无参考图'"
    ><UserRound :size="24"
  /></span>
</template>
<style scoped>
.avatar {
  flex-shrink: 0;
}
</style>
