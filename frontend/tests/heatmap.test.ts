import { describe, expect, it } from 'vitest';
import { calendarDays, dayQuery, heatmapRange, heatmapScale } from '../src/heatmap';
import { emptyFilter } from '../src/filters';

function bandSizes(counts: number[]) {
  const bands = heatmapScale(counts);
  return bands.slice(1).map((band, index) => counts.filter(count => count > bands[index].end && count <= band.end).length);
}

describe('heatmap scale', () => {
  it('keeps zero separate even when there are too few distinct positive counts for four bands', () => {
    expect(heatmapScale([]).map(band => band.label)).toEqual(['0']);
    expect(heatmapScale([0, 0]).map(band => band.label)).toEqual(['0']);
    expect(heatmapScale([3, 3, 0]).map(band => band.label)).toEqual(['0', '1–3']);
  });
  it('separates a cluster of high days without reserving a color for the single peak', () => {
    const spread = (low: number, high: number, days: number) => Array.from({ length: days },
      (_, index) => low + Math.floor(index * (high - low) / (days - 1)));
    const counts = [...spread(1, 5, 25), ...spread(6, 11, 25), ...spread(12, 21, 25),
      ...spread(22, 31, 10), ...spread(60, 100, 14), 304];
    const bands = heatmapScale(counts);
    expect(bands.map(band => band.end)).toEqual([0, 4, 11, 59, 304]);
    expect(bandSizes(counts)).toEqual([24, 26, 35, 15]);
    expect(heatmapScale([0, ...counts.slice().reverse(), 0])).toEqual(bands);
  });
  it('breaks equal ratio ties by proximity to the window center, then by lower count', () => {
    const powersOfTwo = (days: number[]) => days.flatMap((size, index) => Array<number>(size).fill(2 ** index));
    expect(bandSizes(powersOfTwo([20, 5, 5, 25, 30, 15]))).toEqual([25, 30, 30, 15]);
    expect(bandSizes(powersOfTwo([20, 10, 25, 30, 15]))).toEqual([20, 35, 30, 15]);
  });
  it('uses the nearest feasible boundary when repeated counts skip a window', () => {
    const counts = [...Array<number>(65).fill(1), 2, 2, 3, 3, 3, ...Array<number>(15).fill(4), ...Array<number>(15).fill(100)];
    expect(bandSizes(counts)).toEqual([65, 2, 18, 15]);
  });
  it('redistributes only unused counts, balancing widths between forced boundaries', () => {
    expect(heatmapScale([4, 4, 20]).map(band => band.label)).toEqual(['0', '1–10', '11–20']);
    const ends = (counts: number[]) => heatmapScale(counts).map(band => band.end);
    expect(ends([1, 2, 50, 100])).toEqual([0, 1, 34, 67, 100]);
    expect(ends([1, 50, 99, 100])).toEqual([0, 33, 66, 99, 100]);
    expect(ends([1, 2, 3, 4])).toEqual([0, 1, 2, 3, 4]);
  });
});

describe('heatmap calendar', () => {
  it('maps leap days and partial weeks to the Monday-first calendar', () => {
    const days = calendarDays(2012);
    expect(days).toHaveLength(366);
    expect(days[0]).toMatchObject({ row: 6, column: 0 });
    expect(days[59].date).toBe('2012-02-29');
    expect(days.at(-1)).toMatchObject({ row: 0, column: 53 });
    expect(calendarDays(2023)).toHaveLength(365);
  });
  it('keeps empty years in explicit bounds but does not invent an open endpoint', () => {
    const start = new Date('2022-10-01T00:00:00').toISOString(), end = new Date('2025-01-01T00:00:00').toISOString();
    expect(heatmapRange(start, end, [])).toEqual({ first: '2022-10-01', last: '2024-12-31', years: [2024, 2023, 2022] });
    expect(heatmapRange('', end, [])).toBeNull();
    expect(heatmapRange(start, '', [{ date: '2024-02-29', new_photos: 0, posts: 1 }])?.last).toBe('2024-02-29');
  });
  it('clips gallery links to bounds and preserves other filters', () => {
    const filter = { ...emptyFilter(), start: new Date('2024-02-29T10:00:00').toISOString(), people: [2, 3], include_no_faces: true };
    expect(dayQuery(filter, '2024-02-29')).toEqual({ people: '2-3', include_no_faces: 'true', start: filter.start, end: new Date('2024-03-01T00:00:00').toISOString() });
  });
});
