import type { Settings } from './use-game-room';
import { filterOnlyQuery, type Filter } from './filters';

export function parseRules(query: Record<string, unknown>, history: boolean): Settings {
  function number(key: string, fallback: number, min: number, max: number, integer = true) {
    const value = Number(query[key]);
    return query[key] != null && query[key] !== '' && Number.isFinite(value) && value >= min && value <= max && (!integer || Number.isInteger(value)) ? value : fallback;
  }
  const life = !history && query.mode === 'life';
  return { single_life: life, round_limit: life || query.mode === 'endless' ? 0 : number('round_limit', 25, 1, 999),
    answer_seconds: number('answer_seconds', 15, 3, 300), cropped: !history && query.cropped !== 'false',
    grid: !history && query.grid === 'true', grid_size: number('grid_size', 5, 2, 16), grid_seconds: number('grid_seconds', 0.5, 0.1, 60, false),
    continue_seconds: number('continue_seconds', 10, 0, 300), allow_late_join: query.allow_late_join !== 'false' };
}

export function ruleQuery(settings: Settings, filter: Filter, history: boolean, multiplayer = false) {
  const query: Record<string, string> = { people: '', publishers: '', match: 'any', start: '', end: '', include_no_faces: 'false', ...filterOnlyQuery(filter),
    mode: settings.single_life ? 'life' : settings.round_limit ? 'fixed' : 'endless', answer_seconds: String(settings.answer_seconds) };
  if (query.mode === 'fixed') query.round_limit = String(settings.round_limit);
  if (!history) Object.assign(query, { cropped: String(settings.cropped), grid: String(settings.grid) });
  if (!history && settings.grid) Object.assign(query, { grid_size: String(settings.grid_size), grid_seconds: String(settings.grid_seconds) });
  if (multiplayer) Object.assign(query, { continue_seconds: String(settings.continue_seconds), ...(!settings.single_life && { allow_late_join: String(settings.allow_late_join) }) });
  return query;
}
