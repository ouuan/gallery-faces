<script setup lang="ts">
import { localRangeLabel } from "./date-range";
defineProps<{ start: string; end: string }>();
</script>
<template><p class="hint date-range-hint" role="status">{{ localRangeLabel(start, end) }}</p></template>
