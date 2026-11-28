<script setup lang="ts">
import { onMounted, ref } from "vue";
import { NButton } from "naive-ui";
import { RefreshCw } from "@lucide/vue";
import { api, dateLabel } from "./api";
import type { components } from "./schema";

const status = ref<components["schemas"]["CacheStatus"] | null>(null);
const loading = ref(false);
const error = ref("");
const number = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });
const percent = new Intl.NumberFormat("zh-CN", { style: "percent", maximumFractionDigits: 1 });
const hitRate = (hits: number, misses: number) => hits + misses ? percent.format(hits / (hits + misses)) : "暂无读取";
const size = (bytes: number | null) => bytes === null ? "未知" : `${number.format(bytes / 2 ** 30)} GiB`;
const date = (seconds: number) => dateLabel(new Date(seconds * 1000).toISOString());
const label = (folder: string) => folder === "images" ? "展示图" : "原图";
const outcome = { target: "已达到目标", exhausted: "无更多可淘汰文件", error: "清理中断" };

async function refresh() {
  if (loading.value) return;
  loading.value = true;
  error.value = "";
  try { status.value = await api("/admin/media-cache"); }
  catch (cause) { error.value = (cause as Error).message; }
  finally { loading.value = false; }
}
onMounted(refresh);
</script>

<template>
  <section class="cache" aria-labelledby="cache-heading">
    <header><h2 id="cache-heading">图片磁盘缓存</h2>
      <n-button size="small" :loading="loading" :disabled="loading" @click="refresh">
        <template #icon><RefreshCw :size="15" /></template>刷新状态
      </n-button>
    </header>
    <p v-if="error" role="alert">缓存状态加载失败：{{ error }}</p>
    <p v-if="loading && !status" class="hint" role="status">正在读取缓存状态…</p>
    <template v-if="status">
      <p v-if="!status.config">尚未收到 worker 的缓存配置</p>
      <p v-else-if="status.config.low_bytes === null">自动清理未启用</p>
      <p v-else>自动清理已启用：每块盘低于 <strong>{{ size(status.config.low_bytes) }}</strong> 时开始，清至 <strong>{{ size(status.config.target_bytes) }}</strong> 可用空间</p>
      <p v-if="status.config">近期使用保护：<strong>{{ status.config.min_idle_seconds == null ? '未上报' : status.config.min_idle_seconds === 0 ? '已关闭（0 小时）' : `${status.config.min_idle_seconds / 3600} 小时` }}</strong></p>
      <table><caption>源站缓存读取（最近 24 小时）</caption>
        <thead><tr><th scope="col">类型</th><th scope="col">命中率</th><th scope="col">命中</th><th scope="col">未命中</th><th scope="col">成功恢复</th></tr></thead>
        <tbody><tr v-for="item in status.activity_24h" :key="item.folder"><th scope="row">{{ label(item.folder) }}</th><td>{{ hitRate(item.hits, item.misses) }}</td><td>{{ number.format(item.hits) }}</td><td>{{ number.format(item.misses) }}</td><td>{{ number.format(item.recoveries) }}</td></tr></tbody>
      </table>
      <table><caption>当前文件数（不含回收站）</caption>
        <thead><tr><th scope="col">类型</th><th scope="col">在盘</th><th scope="col">已淘汰</th><th scope="col">已丢失</th><th scope="col">缺失</th><th v-if="status.inventory?.some(item => item.unknown)" scope="col">未核实</th></tr></thead>
        <tbody><tr v-for="item in status.inventory" :key="item.folder"><th scope="row">{{ label(item.folder) }}</th><td>{{ number.format(item.present) }}</td><td>{{ number.format(item.evicted) }}</td><td>{{ item.folder === 'originals' ? number.format(item.lost) : '—' }}</td><td>{{ number.format(item.missing) }}</td><td v-if="status.inventory.some(row => row.unknown)">{{ number.format(item.unknown) }}</td></tr></tbody>
      </table>
      <div v-for="volume in status.volumes" :key="volume.folders.join('/')" class="volume">
        <div class="volume-heading"><h3>{{ volume.folders.join(' · ') }}</h3><span>可用 {{ size(volume.free_bytes) }}</span></div>
        <template v-if="volume.last_cleanup">
          <p>上次清理：{{ date(volume.last_cleanup.finished_at) }} · {{ outcome[volume.last_cleanup.outcome] }}</p>
          <p class="hint">可用空间：{{ size(volume.last_cleanup.before_bytes) }} → {{ size(volume.last_cleanup.after_bytes) }}，当次目标 {{ size(volume.last_cleanup.target_bytes) }}</p>
          <table v-if="Object.keys(volume.last_cleanup.removals).length" aria-label="上次清理的实际淘汰阈值">
            <thead><tr><th scope="col">类型</th><th scope="col">淘汰张数</th><th scope="col">最短闲置</th><th scope="col">最低分</th></tr></thead>
            <tbody><tr v-for="(item, folder) in volume.last_cleanup.removals" :key="folder"><th scope="row">{{ label(folder) }}</th><td>{{ number.format(item.count) }}</td><td>{{ item.min_idle_days === null ? '—' : `${number.format(item.min_idle_days)} 天` }}</td><td>{{ item.min_score === null ? '—' : number.format(item.min_score) }}</td></tr></tbody>
          </table>
        </template>
        <p v-else class="hint">暂无清理记录</p>
      </div>
      <details><summary>淘汰规则</summary><p>文件闲置达到保护时长后才可淘汰。展示图按闲置天数 × 4 评分；原图按闲置天数 × 0.25 至 1 评分，发布日期越近，权重越低。同盘优先淘汰高分文件。</p><p>最短闲置天数和最低分分别取自当次实际淘汰的文件，不是固定配置</p></details>
    </template>
  </section>
</template>

<style scoped>
.cache { max-width: 46rem; margin-block: 32px; font-variant-numeric: tabular-nums; }
header, .volume-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 6px 16px; }
h2, h3 { margin: 0; }
p { margin: 8px 0; }
table { border-collapse: collapse; width: 100%; margin-block: 12px; }
caption { text-align: start; font-weight: 600; margin-bottom: 4px; }
td, th { padding: 6px 4px; text-align: end; border-bottom: 1px solid var(--line); }
th:first-child { text-align: start; }
thead th { color: var(--muted); font-weight: 500; }
.volume { margin-top: 20px; }
.volume-heading h3 { font-size: 1rem; }
details { margin-top: 16px; color: var(--muted); }
summary { cursor: pointer; }
</style>
