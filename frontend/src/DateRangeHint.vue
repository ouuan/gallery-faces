<script setup lang="ts">
import { t, ja } from "./locale";
import { rangeError } from "./date-range";
defineProps<{ start: string; end: string }>();
</script>
<template><p class="hint date-range-hint" role="status">{{ rangeError(start, end) || t("包含开始，不含结束") }}</p></template>
