import { reactive } from 'vue';
import type { components } from './schema';
import { faceDisplay, gridOrder, type FaceDisplay } from './face-grid';

export type Question = components['schemas']['GameQuestion'];
export type Outcome = 'correct' | 'wrong' | 'disputed';
export type Round = { question: Question; choice?: number | null; index: number; key: number; order?: number[]; started?: number };
export const game = reactive<{ filter: string | null; round: Round | null; outcomes: Outcome[]; display: FaceDisplay; correctCells: number }>({
  filter: null, round: null, outcomes: [], display: faceDisplay(), correctCells: 0,
});

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

export function score(outcomes: Outcome[]) {
  let correct = 0, wrong = 0, disputed = 0, streak = 0;
  for (const outcome of outcomes) {
    if (outcome === 'correct') { correct++; streak++; }
    else if (outcome === 'wrong') { wrong++; streak = 0; }
    else disputed++;
  }
  return { correct, wrong, disputed, streak, accuracy: correct + wrong ? `${Math.round(100 * correct / (correct + wrong))}%` : '—' };
}

export function cropBox(box: number[], width: number, height: number) {
  const left = Math.max(0, Math.min(width - 1, box[0]!)), top = Math.max(0, Math.min(height - 1, box[1]!));
  return [left, top, Math.max(1, Math.min(width, box[0]! + box[2]!) - left),
    Math.max(1, Math.min(height, box[1]! + box[3]!) - top)] as const;
}

let sequence = 0;
export function openRound(question: Question) {
  game.round = { question, index: game.outcomes.length, key: ++sequence, order: game.display.grid ? gridOrder(game.display.grid_size) : undefined };
}

export function correctChoice(question: Question) {
  return question.choices.find(choice => choice.id === question.face.person_id)?.id ?? null;
}

export function answer(choice: number | null, cells = 0) {
  const round = game.round;
  if (!round || round.choice !== undefined) return;
  round.choice = choice;
  const correct = choice === correctChoice(round.question);
  if (correct) game.correctCells += cells;
  game.outcomes.push(correct ? 'correct' : 'wrong');
}

export function feedbackReceipt(round: Round, outcomes: Outcome[]) {
  return (faceId: number | null) => {
    if (faceId === round.question.face.id && outcomes[round.index] === 'wrong') outcomes[round.index] = 'disputed';
  };
}
