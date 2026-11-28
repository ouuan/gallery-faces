export type FaceDisplay = { cropped: boolean; grid: boolean; grid_size: number; grid_seconds: number };
export const defaultGrid = { grid_size: 10, grid_seconds: 0.2 };

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
