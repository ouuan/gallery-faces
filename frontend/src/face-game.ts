export function faceAccuracy(correct: number, wrong: number, disputed = 0) {
  const counted = correct + wrong - disputed;
  return counted > 0 ? `${Math.round(100 * correct / counted)}%` : '—';
}

export function faceZoom(box: number[], width: number, height: number) {
  const scale = Math.max(1, Math.min(width / (2 * box[2]!), height / (2 * box[3]!)));
  const offset = (center: number) => Math.max(1 - scale, Math.min(0, 0.5 - center * scale));
  return { scale, left: offset((box[0]! + box[2]! / 2) / width), top: offset((box[1]! + box[3]! / 2) / height) };
}

export function gridViewport(box: number[], width: number, height: number) {
  const { scale } = faceZoom(box, width, height);
  const short = Math.min(width, height) / scale;
  const viewWidth = Math.min(width / scale, Math.max(short, 2 * box[2]!));
  const viewHeight = Math.min(height / scale, Math.max(short, 2 * box[3]!));
  const left = Math.max(0, Math.min(width - viewWidth, box[0]! + box[2]! / 2 - viewWidth / 2));
  const top = Math.max(0, Math.min(height - viewHeight, box[1]! + box[3]! / 2 - viewHeight / 2));
  return [left, top, viewWidth, viewHeight] as const;
}

export function cropBox(box: number[], width: number, height: number) {
  const left = Math.max(0, Math.min(width - 1, box[0]!)), top = Math.max(0, Math.min(height - 1, box[1]!));
  return [left, top, Math.max(1, Math.min(width, box[0]! + box[2]!) - left),
    Math.max(1, Math.min(height, box[1]! + box[3]!) - top)] as const;
}
