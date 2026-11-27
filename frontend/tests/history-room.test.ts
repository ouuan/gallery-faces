import { expect, test } from 'vitest';
import { closestResult, compareHistory } from '../src/history-quiz';

const history = { photo: null, my_guess: null, correct_date: '2026-01-10', settled: 2,
  guesses: { 1: '2026-01-09', 2: '2026-01-11' }, closest: [1, 2],
  scores: { 1: 1.5, 2: 0.5, 3: 0.5 }, total_deviations: { 1: 12, 2: 8, 3: 3 } };
const players = [{ id: 1, name: '甲' }, { id: 2, name: '乙' }, { id: 3, name: '丙' }];

test('points take priority over total deviation; equal records share a rank', () => {
  expect([2, 3, 1].sort((first, second) => compareHistory(history, first, second))).toEqual([1, 3, 2]);
  expect(compareHistory({ ...history, total_deviations: { 2: 3, 3: 3 } }, 2, 3)).toBe(0);
});

test('reveal names the closest players and avoids repeating the viewer’s own result', () => {
  expect(closestResult(history, players, 3)).toBe('甲、乙并列最接近 · 相差 1 天');
  expect(closestResult(history, players, 2)).toBe('你和甲并列最接近');
  expect(closestResult({ ...history, closest: [1] }, players, 1)).toBe('你猜得最接近');
  expect(closestResult({ ...history, closest: [] }, players, 1)).toBe('本题无人作答，不计分');
});

test.each([
  ['2026-01-09', '早了 1 天'],
  ['2026-01-11', '晚了 1 天'],
  ['2026-01-10', '正好猜中'],
])('reveal describes the shared closest date %s', (date, detail) => {
  const round = { ...history, guesses: { 1: date, 2: date, 3: '2026-01-07' } };
  expect(closestResult(round, players, 3)).toBe(`甲、乙并列最接近 · ${detail}`);
  expect(closestResult({ ...round, closest: [1], guesses: { 1: date } }, players, 3)).toBe(`甲最接近 · ${detail}`);
});
