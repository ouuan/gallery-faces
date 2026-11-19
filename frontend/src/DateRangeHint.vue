<script setup lang="ts">
import { computed } from "vue";
import { rangeError } from "./date-range";
const props = defineProps<{ start: string; end: string }>();
const error = computed(() => rangeError(props.start, props.end));
</script>
<template><p v-if="error" class="hint date-range-hint" role="status">{{ error }}</p></template>
