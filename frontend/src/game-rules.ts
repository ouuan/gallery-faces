import type { Settings } from './use-game-room';
import { filterOnlyQuery, type Filter } from './filters';
import { defaultGrid } from './face-grid';

export function parseRules(query: Record<string, unknown>, history: boolean): Settings {
  function number(raw: unknown, fallback: number, min: number, max: number, integer = true) {
    const value = Number(raw);
    return typeof raw === 'string' && raw.trim() !== '' && Number.isFinite(value) && value >= min && value <= max && (!integer || Number.isInteger(value)) ? value : fallback;
  }
  const life = !history && query.n === 'life';
  const grid = typeof query.grid === 'string' && /^(\d+)x(\d+(?:\.\d+)?)$/.exec(query.grid);
  const size = number(grid && grid[1], defaultGrid.grid_size, 2, 16);
  return { single_life: life, round_limit: life ? 0 : number(query.n, 25, 0, 999),
    answer_seconds: number(query.t, 15, 3, 300), cropped: !history && query.crop !== '0',
    grid: !history && query.grid !== 'off', grid_size: size,
    grid_cells: number(!history && query.grid !== 'off' && query.cells, size ** 2, 1, size ** 2),
    grid_seconds: number(grid && grid[2], defaultGrid.grid_seconds, 0.1, 60, false),
    continue_seconds: number(query.next, 10, 0, 300), allow_late_join: !life && query.join !== '0' };
}

export function ruleQuery(settings: Settings, filter: Filter, history: boolean, multiplayer = false) {
  const query = filterOnlyQuery(filter);
  query.n = !history && settings.single_life ? 'life' : String(settings.round_limit);
  query.t = String(settings.answer_seconds);
  if (!history) {
    query.crop = settings.cropped ? '1' : '0';
    query.grid = settings.grid ? `${settings.grid_size}x${settings.grid_seconds}` : 'off';
    if (settings.grid && settings.grid_cells !== settings.grid_size ** 2) query.cells = String(settings.grid_cells);
  }
  if (multiplayer) {
    query.next = String(settings.continue_seconds);
    if (!settings.single_life) query.join = settings.allow_late_join ? '1' : '0';
  }
  return query;
}
