<script setup lang="ts">
import LoadingOverlay from "./LoadingOverlay.vue";
import { computed, ref } from "vue";
import { useReviewImages } from "./use-review-images";

const props = defineProps<{
  image: { id: number; width: number; height: number; faces: any[] };
  modelValue: string;
  disabled?: boolean;
}>();
const emit = defineEmits<{ "update:modelValue": [value: string] }>();
const { urls, failed } = useReviewImages(() => [props.image.id]);
const photo = ref<HTMLImageElement>();
const surface = ref<HTMLDivElement>();
const drag = ref<{
  pointer: number;
  start: [number, number];
  previous: string;
} | null>(null);
const draft = computed(() => {
  const values = props.modelValue.split(",").map(Number);
  if (values.length !== 4 || !values.every(Number.isFinite)) return null;
  const [x, y, width, height] = values as [number, number, number, number];
  return x >= 0 &&
    y >= 0 &&
    width > 0 &&
    height > 0 &&
    x + width <= props.image.width &&
    y + height <= props.image.height
    ? values
    : null;
});
function style(box: number[]) {
  return {
    left: `${(box[0]! / props.image.width) * 100}%`,
    top: `${(box[1]! / props.image.height) * 100}%`,
    width: `${(box[2]! / props.image.width) * 100}%`,
    height: `${(box[3]! / props.image.height) * 100}%`,
  };
}
function point(event: PointerEvent): [number, number] {
  const bounds = photo.value!.getBoundingClientRect();
  return [
    Math.round(
      Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)) *
        props.image.width,
    ),
    Math.round(
      Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)) *
        props.image.height,
    ),
  ];
}
function start(event: PointerEvent) {
  if (
    props.disabled ||
    !urls.value.has(props.image.id) ||
    failed.value.has(props.image.id) ||
    drag.value ||
    !event.isPrimary ||
    event.button !== 0 ||
    !photo.value?.naturalWidth
  )
    return;
  event.preventDefault();
  surface.value!.focus({ preventScroll: true });
  surface.value!.setPointerCapture(event.pointerId);
  drag.value = {
    pointer: event.pointerId,
    start: point(event),
    previous: props.modelValue,
  };
}
function move(event: PointerEvent) {
  if (drag.value?.pointer !== event.pointerId) return;
  const [x, y] = point(event),
    [sx, sy] = drag.value.start;
  emit(
    "update:modelValue",
    [Math.min(x, sx), Math.min(y, sy), Math.abs(x - sx), Math.abs(y - sy)].join(
      ",",
    ),
  );
}
function release() {
  const pointer = drag.value?.pointer;
  drag.value = null;
  if (pointer !== undefined && surface.value?.hasPointerCapture(pointer))
    surface.value.releasePointerCapture(pointer);
}
function finish(event: PointerEvent) {
  if (drag.value?.pointer !== event.pointerId) return;
  const [x, y] = point(event),
    [sx, sy] = drag.value.start;
  const bounds = photo.value!.getBoundingClientRect();
  // Ignore clicks and tiny accidental drags; keep any previous draft.
  if (
    (Math.abs(x - sx) * bounds.width) / props.image.width < 4 ||
    (Math.abs(y - sy) * bounds.height) / props.image.height < 4
  )
    emit("update:modelValue", drag.value.previous);
  else move(event);
  release();
}
function cancelDrag(event: PointerEvent) {
  if (drag.value?.pointer !== event.pointerId) return;
  emit("update:modelValue", drag.value.previous);
  release();
}
function clear() {
  release();
  emit("update:modelValue", "");
}
</script>

<template>
  <div
    ref="surface"
    class="annotated-image face-box-editor"
    :style="{ aspectRatio: `${image.width} / ${image.height}` }"
    :aria-busy="!urls.has(image.id) && !failed.has(image.id)"
    :class="{ disabled }"
    tabindex="0"
    role="group"
    aria-label="拖拽框选人脸；按 Escape 取消"
    :aria-disabled="disabled"
    @pointerdown="start"
    @pointermove="move"
    @pointerup="finish"
    @pointercancel="cancelDrag"
    @lostpointercapture="cancelDrag"
    @keydown.esc.stop.prevent="!disabled && clear()"
  >
    <img
      :key="image.id"
      ref="photo"
      :src="!failed.has(image.id) && urls.get(image.id) || `/api/v1/admin/media/${image.id}?thumbnail=true`"
      alt="正在审核的原图"
      :draggable="false"
      @error="urls.has(image.id) && failed.add(image.id)"
    />
    <LoadingOverlay :show="failed.has(image.id) || !urls.has(image.id)" center :error="failed.has(image.id)" :label="failed.has(image.id) ? '图片加载失败' : '正在加载图片…'" />
    <span
      v-for="face in image.faces"
      :key="face.id"
      class="face-box"
      :class="{ ignored: face.ignored }"
      :style="style(face.box)"
      >#{{ face.id }}</span
    >
    <span v-if="draft" class="face-box draft-box" :style="style(draft)"
      ><span>待保存</span></span
    >
  </div>
</template>

<style scoped>
.face-box-editor {
  cursor: crosshair;
  touch-action: none;
  user-select: none;
}
.face-box-editor.disabled {
  cursor: wait;
}
.face-box-editor .face-box {
  pointer-events: none;
}
.draft-box {
  border-style: dashed;
}
.draft-box > span {
  display: inline-block;
  padding: 2px 4px;
  color: white;
  background: var(--accent);
  text-shadow: none;
  white-space: nowrap;
}
</style>
