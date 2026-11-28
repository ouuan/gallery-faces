import type { components } from './schema';

export type HistoryPhoto = components['schemas']['HistoryPhoto'];
const millisecondsPerDay = 86_400_000;
export const dayNumber = (date: string) => Date.parse(`${date}T00:00:00Z`) / millisecondsPerDay;
export const dayLabel = (day: number) => new Date(day * millisecondsPerDay).toISOString().slice(0, 10);
export const middleDay = (photo: HistoryPhoto) => Math.floor((dayNumber(photo.first_date) + dayNumber(photo.last_date)) / 2);
export const average = (total: number, count: number) => count ? `${(total / count).toFixed(1)} 天` : '—';
export const formatPoints = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 5 }).format;
type HistoryStatus = components['schemas']['HistoryStatus'];
export function compareHistory(history: HistoryStatus, first: number, second: number) {
  return history.scores[second]! - history.scores[first]! || history.total_deviations[first]! - history.total_deviations[second]!;
}
export function closestResult(history: HistoryStatus, players: { id: number; name: string }[], me: number) {
  const { closest, correct_date, guesses } = history;
  if (!closest || !correct_date || !guesses) return '';
  if (!closest.length) return '本题无人作答，不计分';
  const others = players.filter(player => player.id !== me && closest.includes(player.id)).map(player => player.name).join('、');
  if (closest.includes(me)) return others ? `你和${others}并列最接近` : '你猜得最接近';
  const firstGuess = guesses[closest[0]!]!;
  const detail = closest.some(id => guesses[id] !== firstGuess)
    ? `相差 ${Math.abs(dayNumber(firstGuess) - dayNumber(correct_date))} 天`
    : firstGuess === correct_date ? '正好猜中' : difference(firstGuess, correct_date);
  return `${others}${closest.length > 1 ? '并列' : ''}最接近 · ${detail}`;
}
export function difference(guess: string, correct: string) {
  const days = dayNumber(guess) - dayNumber(correct);
  return days ? `${days < 0 ? '早' : '晚'}了 ${Math.abs(days)} 天` : '正好';
}
