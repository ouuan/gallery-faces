<script setup lang="ts">
import { rangeError } from "./date-range";
defineProps<{ start: string; end: string }>();
</script>
<template><p class="hint date-range-hint" role="status">{{ rangeError(start, end) || "包含开始，不含结束" }}</p></template>
