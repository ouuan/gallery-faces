<script setup lang="ts">
import type { Settings } from './use-game-room';
defineProps<{ settings: Settings; history?: boolean; solo?: boolean }>();
</script>

<template>
  <section aria-label="对战规则" class="room-rules">
    <h3>对战规则</h3>
    <p>{{ settings.single_life ? '一命模式' : settings.round_limit ? `固定局数 · 共 ${settings.round_limit} 题` : '无尽模式' }}</p>
    <p v-if="history">史官测验 · 每题 {{ settings.answer_seconds }} 秒</p>
    <p v-else-if="settings.grid">{{ settings.cropped ? '仅截取人脸' : '人脸及周围' }} · 逐格显示 · {{ settings.grid_size }}×{{ settings.grid_size }} · 每格 {{ settings.grid_seconds }} 秒 · 显示 {{ settings.grid_cells }} 格后还有 {{ settings.answer_seconds }} 秒作答</p>
    <p v-else>{{ settings.cropped ? '仅截取人脸' : '全图' }} · 直接显示 · 每题 {{ settings.answer_seconds }} 秒</p>
    <p>参赛者加载照片后开始，最多等 5 秒</p>
    <p v-if="history && solo">未答按居中日期计算偏差。</p>
    <p v-else-if="history">每题猜得最接近的人得 1 分，并列则均分。分数相同时，平均偏差小的排在前面。未答不得分，按居中日期计算偏差。</p>
    <p v-if="!solo">{{ settings.continue_seconds ? `${settings.continue_seconds} 秒后切题` : '全员继续后切题' }} · {{ settings.single_life ? (settings.grid ? '一命模式，仅答错淘汰' : '一命模式，答错或未答即淘汰') : settings.allow_late_join ? '允许中途加入' : '不允许中途加入' }}</p>
  </section>
</template>

<style scoped>
.room-rules h3 { margin: 0 0 6px; font-size: 1em; }
.room-rules p { margin: 0; }
</style>
