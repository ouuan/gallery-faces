import type { components } from './schema';
import { heatmapColorThemes } from 'naive-ui/es/heatmap/src/theme';
import { filterOnlyQuery, type Filter } from './filters';

export type HeatmapDay = components['schemas']['HeatmapDay'];
export type Metric = 'new_photos' | 'posts';

type Boundary = { min: number; max: number };
type CountGroup = { count: number; cumulativeDays: number };

const windowCenters = [25, 60, 90];
const windowRadius = 5;

function chooseBoundary(groups: CountGroup[], first: number, last: number, center: number, totalDays: number) {
  let best = first, bestOutside = Infinity, bestGap = 0, bestDistance = Infinity;
  for (let index = first; index <= last; index++) {
    const { count, cumulativeDays } = groups[index];
    const distance = Math.abs(100 * cumulativeDays - center * totalDays);
    const outside = Math.max(0, distance - windowRadius * totalDays);
    const gap = groups[index + 1].count - count;
    if (outside < bestOutside || (outside === bestOutside &&
      (gap > bestGap || (gap === bestGap && distance < bestDistance)))) {
      best = index;
      bestOutside = outside;
      bestGap = gap;
      bestDistance = distance;
    }
  }
  return best;
}

function balanceWidths(bounds: Boundary[]) {
  const ends = [0];
  while (ends.length <= bounds.length) {
    const first = ends.length - 1, start = ends[first];
    let minWidth = -Infinity, maxWidth = Infinity, minIndex = first, maxIndex = first;
    let stop = bounds.length, end = bounds[stop - 1].max;
    // Extend an equal-width run until a boundary forces a narrower or wider interval.
    for (let index = first; index < bounds.length; index++) {
      const span = index - first + 1;
      const lower = (bounds[index].min - start) / span, upper = (bounds[index].max - start) / span;
      if (lower > maxWidth) { stop = maxIndex + 1; end = bounds[maxIndex].max; break; }
      if (upper < minWidth) { stop = minIndex + 1; end = bounds[minIndex].min; break; }
      if (lower > minWidth) { minWidth = lower; minIndex = index; }
      if (upper < maxWidth) { maxWidth = upper; maxIndex = index; }
    }
    for (let index = first + 1; index <= stop; index++) {
      ends.push(start + Math.round((end - start) * (index - first) / (stop - first)));
    }
  }
  return ends;
}

export function heatmapScale(counts: number[]) {
  const bands = [{ end: 0, label: '0', color: 'var(--line)' }];
  const colors = heatmapColorThemes.blue;
  const frequencies = new Map<number, number>();
  for (const count of counts) {
    if (count <= 0) continue;
    frequencies.set(count, (frequencies.get(count) ?? 0) + 1);
  }
  let totalDays = 0;
  const groups = [...frequencies].sort(([left], [right]) => left - right).map(([count, days]) => {
    totalDays += days;
    return { count, cumulativeDays: totalDays };
  });
  const bandCount = Math.min(windowCenters.length + 1, colors.length, groups.length);
  const bounds: Boundary[] = [];
  let first = 0;
  for (let index = 0; index < bandCount; index++) {
    const last = groups.length - (bandCount - index);
    const cut = index === bandCount - 1 ? last : chooseBoundary(groups, first, last, windowCenters[index], totalDays);
    const min = groups[cut].count;
    first = cut + 1;
    bounds.push({ min, max: first < groups.length ? groups[first].count - 1 : min });
  }
  const ends = balanceWidths(bounds);
  for (let index = 0; index < bandCount; index++) {
    const start = ends[index] + 1, end = ends[index + 1];
    const color = colors[bandCount === 1 ? colors.length - 1 : Math.round(index * (colors.length - 1) / (bandCount - 1))];
    bands.push({ end, label: start === end ? String(end) : `${start}–${end}`, color });
  }
  return bands;
}
const pad = (number: number, width = 2) => String(number).padStart(width, '0');
function localDate(instant: number) {
  const date = new Date(instant);
  return `${pad(date.getFullYear(), 4)}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function heatmapRange(start: string, end: string, days: HeatmapDay[]) {
  const first = start ? localDate(Date.parse(start)) : days[0]?.date;
  const last = end ? localDate(Date.parse(end) - 1) : days.at(-1)?.date;
  if (!first || !last || first > last) return null;
  const latest = Number(last.slice(0, 4));
  return { first, last, years: Array.from({ length: latest - Number(first.slice(0, 4)) + 1 }, (_, index) => latest - index) };
}

export function calendarDays(year: number) {
  const cursor = new Date(`${pad(year, 4)}-01-01T00:00:00Z`);
  const offset = (cursor.getUTCDay() + 6) % 7;
  let index = offset;
  const days = [];
  while (cursor.getUTCFullYear() === year) {
    const date = cursor.toISOString().slice(0, 10);
    const timestamp = +new Date(date + 'T00:00:00');
    if (localDate(timestamp) === date) days.push({ date, timestamp, column: Math.floor(index / 7), row: index % 7 });
    cursor.setUTCDate(cursor.getUTCDate() + 1);
    index++;
  }
  return days;
}

export function dayQuery(filter: Filter, date: string) {
  const start = new Date(date + 'T00:00:00');
  const nextDate = new Date(date + 'T00:00:00Z');
  nextDate.setUTCDate(nextDate.getUTCDate() + 1);
  const end = new Date(nextDate.toISOString().split('T')[0] + 'T00:00:00');
  return filterOnlyQuery({ ...filter,
    start: filter.start && Date.parse(filter.start) > +start ? filter.start : start.toISOString(),
    end: filter.end && Date.parse(filter.end) < +end ? filter.end : end.toISOString(),
  });
}
