export type FaceDisplay = { cropped: boolean; grid: boolean; grid_size: number; grid_seconds: number };

export function faceDisplay(saved?: Partial<FaceDisplay> | null, cropped = true): FaceDisplay {
  const size = saved?.grid_size, seconds = saved?.grid_seconds;
  return { cropped: typeof saved?.cropped === 'boolean' ? saved.cropped : cropped, grid: saved?.grid === true,
    grid_size: size !== undefined && Number.isInteger(size) && size >= 2 && size <= 16 ? size : 5,
    grid_seconds: typeof seconds === 'number' && seconds >= 0.1 && seconds <= 60 ? seconds : 0.5 };
}

export function gridOrder(size: number) {
  const order = Array.from({ length: size ** 2 }, (_, index) => index);
  for (let index = order.length - 1; index > 0; index--) {
    const other = Math.floor(Math.random() * (index + 1));
    [order[index], order[other]] = [order[other]!, order[index]!];
  }
  return order;
}

export function visibleCells(elapsed: number, seconds: number, total: number) {
  return Math.min(total, Math.floor(Math.max(0, elapsed) / (seconds * 1000)));
}

export function averageCells(total: number, correct: number) {
  return correct ? `${(total / correct).toFixed(1)} 格` : '—';
}

type Record = { correct: number; wrong: number; correct_cells?: number };
export function compareGrid(first: Record, second: Record) {
  return (second.correct - second.wrong) - (first.correct - first.wrong) || second.correct - first.correct
    || (first.correct_cells ?? 0) - (second.correct_cells ?? 0);
}
