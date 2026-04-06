import test from 'node:test';
import assert from 'node:assert/strict';
import { buildSeedRequests } from '../userSync.mjs';

test('buildSeedRequests returns all seeds when existing is empty', () => {
  const seeds = [
    { username: 'alpha', name: 'Alpha User' },
    { username: 'beta', name: 'Beta User' },
  ];

  const out = buildSeedRequests([], seeds);
  assert.deepEqual(out, seeds);
});

test('buildSeedRequests skips usernames already present', () => {
  const existing = [{ id: '1', username: 'alpha', name: 'A' }];
  const seeds = [
    { username: 'alpha', name: 'Alpha User' },
    { username: 'beta', name: 'Beta User' },
  ];

  const out = buildSeedRequests(existing, seeds);
  assert.deepEqual(out, [{ username: 'beta', name: 'Beta User' }]);
});
