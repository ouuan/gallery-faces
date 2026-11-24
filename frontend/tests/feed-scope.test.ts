import { expect, it } from 'vitest';
import { importScopePlatforms } from '../src/feed-scope';

it('activates only account and list targets', () => {
  expect(importScopePlatforms(['https://www.twitter.com/i/lists/123/?s=20', 'https://www.instagram.com/alice.b/'])).toEqual(new Set(['x', 'instagram']));
  expect(importScopePlatforms(['https://x.com/alice'])).toEqual(new Set(['x']));
  expect(importScopePlatforms(['invalid', 'https://instagram.com/p/abc', 'https://x.com/user/status/123',
    'https://x.com/user/media', 'https://instagram.com/alice/posts', 'https://instagram.com/explore',
    'https://x.com/search', 'https://x.com/i/lists/abc', 'https://other.example/alice'])).toEqual(new Set());
});
