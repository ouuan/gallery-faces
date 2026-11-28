<script setup lang="ts">
import type { Settings } from './use-game-room';
defineProps<{ settings: Settings; history?: boolean }>();
</script>

<template>
  <section aria-label="对战规则" class="room-rules">
    <h3>对战规则</h3>
    <p>{{ settings.round_limit ? `固定局数 · 共 ${settings.round_limit} 题` : '无尽模式' }}</p>
    <p v-if="history">史官测验 · 每题 {{ settings.answer_seconds }} 秒</p>
    <p v-else-if="settings.grid">{{ settings.cropped ? '只看人脸' : '人脸及周围' }} · 逐格显示 · {{ settings.grid_size }}×{{ settings.grid_size }} · 每格 {{ settings.grid_seconds }} 秒 · 不限时抢答</p>
    <p v-else>{{ settings.cropped ? '只看人脸' : '全图' }} · 直接显示 · 每题 {{ settings.answer_seconds }} 秒</p>
    <p v-if="settings.grid">全员加载照片后开始，最多等 5 秒。答对 +1 分，答错 −1 分，可继续抢答。</p>
    <p v-if="history">每题猜得最接近的人得 1 分，并列则均分。分数相同时，平均偏差小的排在前面。未答不得分，按居中日期计算偏差。</p>
    <p>{{ settings.continue_seconds ? `${settings.continue_seconds} 秒后切题` : '全员继续后切题' }} · {{ settings.single_life ? '一命模式，答错或未答即淘汰，开局后不可加入' : settings.allow_late_join ? '允许中途加入' : '不允许中途加入' }}</p>
  </section>
</template>

<style scoped>
.room-rules h3 { margin: 0 0 6px; font-size: 1em; }
.room-rules p { margin: 0; }
</style>
