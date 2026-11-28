<script setup lang="ts">
import { NInputNumber, NSwitch } from 'naive-ui';
import type { Settings } from './use-game-room';
import FaceDisplayMode from './FaceDisplayMode.vue';
import GameRoundLimit from './GameRoundLimit.vue';
const model = defineModel<Settings>({ required: true });
defineProps<{ history?: boolean; solo?: boolean }>();
</script>
<template>
  <fieldset class="room-settings"><legend>{{ solo ? '玩法设置' : '房间设置' }}</legend>
    <GameRoundLimit v-if="!model.single_life" :model-value="model.round_limit" @update:model-value="round_limit => model = { ...model, round_limit }" />
    <FaceDisplayMode v-if="!history" :model-value="model" @update:model-value="value => model = { ...model, ...value }" />
    <div class="timing">
    <label>每题答题时间（秒）<n-input-number aria-label="每题答题时间" :value="model.answer_seconds" :min="3" :max="300" @update:value="value => model = { ...model, answer_seconds: value ?? 15 }" /></label>
    <label v-if="!solo">切题秒数（0 关闭）<n-input-number aria-label="自动切题等待" :value="model.continue_seconds" :min="0" :max="300" @update:value="value => model = { ...model, continue_seconds: value ?? 0 }" /></label>
    </div>
    <div class="face-options">
      <label v-if="!history" class="display"><span><n-switch aria-label="一命模式" :value="model.single_life" @update:value="value => model = { ...model, single_life: value, round_limit: value ? 0 : 25 }" /> 一命模式</span></label>
      <label v-if="!solo" class="display"><span><n-switch aria-label="允许中途加入" :aria-disabled="model.single_life" :disabled="model.single_life" :value="!model.single_life && model.allow_late_join" @update:value="value => model = { ...model, allow_late_join: value }" /> 允许中途加入</span></label>
    </div>
  </fieldset>
</template>
<style scoped>
.room-settings { display: grid; gap: 12px; border: 0; padding: 0; min-width: 0; margin: 0; }
.room-settings > legend { font-weight: 700; font-size: 16px; margin-bottom: 12px; }
.timing { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 9rem), 1fr)); align-items: end; gap: 12px; }
label { display: grid; gap: 4px; }
.face-options { display: flex; align-items: end; flex-wrap: wrap; gap: 8px 20px; }
.display span { display: flex; align-items: center; gap: 8px; min-height: 44px; }
@media (max-width: 599px) {
  .room-settings { gap: 8px; }
  .face-options { column-gap: 8px; }
}
</style>
