import { expect, it } from 'vitest';
import { answer, cropBox, faceZoom, feedbackReceipt, game, gridViewport, openRound, score, type Question } from '../src/face-game';
import { averageCells, compareGrid, faceDisplay, gridOrder, visibleCells } from '../src/face-grid';

it('starts covered, reveals one cell per elapsed interval and stops at the full grid', () => {
  const order = gridOrder(5);
  expect(new Set(order)).toEqual(new Set(Array.from({ length: 25 }, (_, index) => index)));
  expect([0, 499, 500, 1000, 12499, 12500, 90000].map(time => visibleCells(time, 0.5, 25))).toEqual([0, 0, 1, 2, 24, 25, 25]);
  expect(faceDisplay({ cropped: false, grid_size: 0, grid_seconds: Infinity })).toEqual({ cropped: false, grid: false, grid_size: 5, grid_seconds: 0.5 });
});

it('ranks by points, wins and exact mean, retaining true ties', () => {
  const record = { correct: 30, wrong: 20, correct_cells: 90 };
  expect(compareGrid(record, { ...record, correct: 31, wrong: 22 })).toBeLessThan(0);
  expect(compareGrid(record, { ...record, correct: 29, wrong: 19 })).toBeLessThan(0);
  expect(averageCells(91, 30)).toBe(averageCells(90, 30));
  expect(compareGrid(record, { ...record, correct_cells: 91 })).toBeLessThan(0);
  expect(compareGrid(record, { ...record })).toBe(0);
  expect(averageCells(0, 0)).toBe('—');
});

it('clips the target to photo edges without stretching or creating an empty viewport', () => {
  expect(cropBox([-5, 80, 40, 40], 100, 100)).toEqual([0, 80, 35, 20]);
  expect(cropBox([100, 100, 0, 0], 100, 100)).toEqual([99, 99, 1, 1]);
});

it('zooms a small face beyond 2x and keeps centered and edge crops inside the photo', () => {
  expect(faceZoom([280, 80, 40, 40], 800, 400)).toEqual({ scale: 5, left: -1.375, top: -.75 });
  expect(faceZoom([760, 360, 40, 40], 800, 400)).toEqual({ scale: 5, left: -4, top: -4 });
});

it('limits zoom by either face dimension without shrinking large faces', () => {
  expect(faceZoom([0, 0, 320, 40], 800, 400).scale).toBe(1.25);
  expect(faceZoom([0, 0, 40, 160], 800, 400).scale).toBe(1.25);
  expect(faceZoom([0, 0, 40, 220], 800, 400)).toEqual({ scale: 1, left: 0, top: 0 });
});

it('trims the magnified long edge towards a square while keeping twice the face extent when possible', () => {
  expect(gridViewport([280, 80, 40, 40], 800, 400)).toEqual([260, 60, 80, 80]);
  expect(gridViewport([300, 100, 150, 100], 800, 400)).toEqual([225, 50, 300, 200]);
  expect(gridViewport([100, 300, 100, 150], 400, 800)).toEqual([50, 225, 200, 300]);
  expect(gridViewport([760, 360, 40, 40], 800, 400)).toEqual([720, 320, 80, 80]);
  expect(gridViewport([0, 0, 500, 200], 800, 400)).toEqual([0, 0, 800, 400]);
});

it('counts a delayed receipt against only its original wrong round', () => {
  const question: Question = { group_id: 1, image_id: 2, width: 100, height: 100, image_url: '/picture', choices: [{ id: 3, name: '甲' }],
    face: { id: 5, person_id: 3, box: [5, 5, 30, 30], revision: 0, locked: false } };
  game.outcomes = [];
  expect(score([]).accuracy).toBe('—');
  openRound(question); answer(3);
  openRound(question); answer(null); answer(3);
  const received = feedbackReceipt(game.round!, game.outcomes);
  openRound(question); answer(3);
  received(null); received(100);
  expect(score(game.outcomes)).toEqual({ correct: 2, wrong: 1, disputed: 0, accuracy: '67%', streak: 1 });
  received(5); received(5);
  feedbackReceipt(game.round!, game.outcomes)(5);
  expect(score(game.outcomes)).toEqual({ correct: 2, wrong: 0, disputed: 1, accuracy: '100%', streak: 2 });
});
