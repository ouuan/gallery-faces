import { expect, it } from 'vitest';
import { cropBox, faceZoom, gridViewport } from '../src/face-game';
import { averageCells, compareGrid, visibleCells } from '../src/face-grid';

it('starts covered, reveals one cell per elapsed interval and stops at the full grid', () => {
  expect([0, 499, 500, 1000, 12499, 12500, 90000].map(time => visibleCells(time, 0.5, 25))).toEqual([0, 0, 1, 2, 24, 25, 25]);
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
