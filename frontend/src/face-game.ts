import { reactive } from 'vue';
import type { components } from './schema';

export type Question = components['schemas']['GameQuestion'];
export type Outcome = 'correct' | 'wrong' | 'disputed';
export type Round = { question: Question; choice?: number | null; index: number; key: number };
export const game = reactive<{ filter: string | null; round: Round | null; outcomes: Outcome[] }>({
  filter: null, round: null, outcomes: [],
});

export function score(outcomes: Outcome[]) {
  let correct = 0, wrong = 0, disputed = 0, streak = 0;
  for (const outcome of outcomes) {
    if (outcome === 'correct') { correct++; streak++; }
    else if (outcome === 'wrong') { wrong++; streak = 0; }
    else disputed++;
  }
  return { correct, wrong, disputed, streak, accuracy: correct + wrong ? `${Math.round(100 * correct / (correct + wrong))}%` : '—' };
}

let sequence = 0;
export function openRound(question: Question) {
  game.round = { question, index: game.outcomes.length, key: ++sequence };
}

export function correctChoice(question: Question) {
  return question.choices.find(choice => choice.id === question.face.person_id)?.id ?? null;
}

export function answer(choice: number | null) {
  const round = game.round;
  if (!round || round.choice !== undefined) return;
  round.choice = choice;
  game.outcomes.push(choice === correctChoice(round.question) ? 'correct' : 'wrong');
}

export function feedbackReceipt(round: Round, outcomes: Outcome[]) {
  return (faceId: number | null) => {
    if (faceId === round.question.face.id && outcomes[round.index] === 'wrong') outcomes[round.index] = 'disputed';
  };
}
