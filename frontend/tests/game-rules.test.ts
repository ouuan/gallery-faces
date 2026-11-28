import { describe, expect, it } from 'vitest';
import { emptyFilter, fromQuery } from '../src/filters';
import { parseRules, ruleQuery } from '../src/game-rules';

describe('game sharing links', () => {
  it('omits all defaults for both games and both player modes', () => {
    for (const history of [false, true]) for (const multiplayer of [false, true]) {
      expect(ruleQuery(parseRules({}, history), emptyFilter(), history, multiplayer)).toEqual({});
    }
  });

  it('round-trips non-default rules and filters from a verbose room link', () => {
    const legacy = { people: '1,2,3', publishers: '', mode: 'fixed', round_limit: '10', answer_seconds: '20', cropped: 'false',
      grid: 'true', grid_size: '8', grid_seconds: '0.25', continue_seconds: '0', allow_late_join: 'false', include_no_faces: 'false' };
    const rules = parseRules(legacy, false), filter = fromQuery(legacy);
    const compact = ruleQuery(rules, filter, false, true);
    expect(compact).toEqual({ people: '1-3', round_limit: '10', answer_seconds: '20', cropped: 'false', grid: 'true',
      grid_size: '8', grid_seconds: '0.25', continue_seconds: '0', allow_late_join: 'false' });
    expect(parseRules(compact, false)).toEqual(rules);
    expect(fromQuery(compact)).toEqual(filter);
  });

  it('keeps the mode but drops options that have no effect', () => {
    const options = { mode: 'life', grid_size: '8', round_limit: '3', continue_seconds: '0', allow_late_join: 'false' };
    expect(ruleQuery(parseRules(options, false), emptyFilter(), false)).toEqual({ mode: 'life' });
    expect(ruleQuery(parseRules({ mode: 'endless', grid: 'true' }, true), emptyFilter(), true)).toEqual({ mode: 'endless' });
  });
});
