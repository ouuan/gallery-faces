import { reactive } from 'vue';
import type { components } from './schema';

export type HistoryPhoto = components['schemas']['HistoryPhoto'];
type Question = components['schemas']['HistoryQuestion'];
const millisecondsPerDay = 86_400_000;
export const dayNumber = (date: string) => Date.parse(`${date}T00:00:00Z`) / millisecondsPerDay;
export const dayLabel = (day: number) => new Date(day * millisecondsPerDay).toISOString().slice(0, 10);
export const middleDay = (photo: HistoryPhoto) => Math.floor((dayNumber(photo.first_date) + dayNumber(photo.last_date)) / 2);
export const average = (total: number, count: number) => count ? `${(total / count).toFixed(1)} 天` : '—';
export function difference(guess: string, correct: string) {
  const days = dayNumber(guess) - dayNumber(correct);
  return days ? `${days < 0 ? '早' : '晚'}了 ${Math.abs(days)} 天` : '正好';
}

export const session = reactive({ scope: null as string | null, question: null as Question | null, guess: '', submitted: false, total: 0, count: 0, early: 0, late: 0 });
export function submit(guess: string) {
  if (!session.question || session.submitted) return;
  session.guess = guess;
  session.submitted = true;
  const offset = dayNumber(guess) - dayNumber(session.question.correct_date);
  if (offset < 0) session.early++;
  if (offset > 0) session.late++;
  session.total += Math.abs(offset);
  session.count++;
}
