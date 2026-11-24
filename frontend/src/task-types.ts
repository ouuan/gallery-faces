export const taskKindLabels: Record<string, string> = {
  download: '链接下载', import: '目录导入', monitor: '发布者监控', detect: '人脸检测',
  rematch: '人物匹配', restore: '图片恢复', avatar: '发布者头像',
};
const children: Record<string, Record<string, string>> = {
  download: { post: '单帖下载', account: '账号／媒体页下载', list: '列表下载' },
  monitor: { monitor_scheduled: '定时更新', monitor_now: '立即更新', monitor_initial: '首次／恢复更新', monitor_backfill: '历史补齐' },
  detect: { auto: '自动人脸检测', highres: '高分辨率重检' },
  rematch: { unknown: '匹配未知人脸', all_faces: '重新匹配全部人脸' },
};
export const taskSubtypeLabels = Object.assign({}, taskKindLabels, ...Object.values(children)) as Record<string, string>;
export const taskTypeOptions = Object.entries(taskKindLabels).map(([key, label]) => ({
  key, label, children: children[key] && Object.entries(children[key]).map(([key, label]) => ({ key, label })),
}));
export const tierLabels: Record<string, string> = {
  avatar: '发布者头像', single: '单帖或单图', scheduled: '定时监控', bulk: '批量处理', maintenance: '全库维护',
};
