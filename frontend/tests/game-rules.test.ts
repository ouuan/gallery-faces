import { describe, expect, it } from 'vitest';
import { emptyFilter, fromQuery } from '../src/filters';
import { parseRules, ruleQuery } from '../src/game-rules';

describe('game sharing links', () => {
  it('writes every effective rule even when starting with the defaults', () => {
    for (const history of [false, true]) for (const multiplayer of [false, true]) {
      const settings = parseRules({}, history);
      const encoded = ruleQuery(settings, emptyFilter(), history, multiplayer);
      expect(encoded).toEqual({ n: '25', t: '15', ...(!history && { crop: '1', grid: '10x0.2' }),
        ...(multiplayer && { next: '10', join: '1' }) });
      expect(parseRules(encoded, history)).toEqual(settings);
    }
  });

  it('round-trips custom room rules and filters', () => {
    const query = { people: '1-3', n: '0', t: '20', crop: '0', grid: '8x0.25', next: '0', join: '0' };
    const settings = parseRules(query, false);
    expect(settings).toMatchObject({ round_limit: 0, answer_seconds: 20, cropped: false, grid_size: 8, grid_seconds: 0.25,
      continue_seconds: 0, allow_late_join: false });
    expect(ruleQuery(settings, fromQuery(query), false, true)).toEqual(query);
  });

  it('encodes direct display and one-life without inactive grid or join options', () => {
    const query = { n: 'life', t: '3', crop: '1', grid: 'off', next: '0' };
    const settings = parseRules(query, false);
    expect(settings).toMatchObject({ single_life: true, round_limit: 0, grid: false, allow_late_join: false });
    expect(ruleQuery(settings, emptyFilter(), false, true)).toEqual(query);
    expect(parseRules({ n: '-1', t: '999', grid: '17x0' }, false)).toEqual(parseRules({}, false));
  });
});
