import test from 'node:test';
import assert from 'node:assert/strict';
import { resolveSessionBinding } from '../src/local-agent/sessionBinding.js';

test('an existing local conversation keeps its original directory snapshot', () => {
  const binding = resolveSessionBinding(
    { directory: '/projects/alpha', providerSessionId: 'provider-a', endpoint: 'http://127.0.0.1:4096' },
    'http://127.0.0.1:4096',
    '/projects/beta',
  );
  assert.equal(binding.directory, '/projects/alpha');
  assert.equal(binding.providerSessionId, 'provider-a');
});

test('a local conversation cannot be silently rebound to another endpoint', () => {
  assert.throws(
    () => resolveSessionBinding(
      { directory: '/projects/alpha', endpoint: 'http://127.0.0.1:4096' },
      'http://127.0.0.1:5096',
      '/projects/beta',
    ),
    /另一个 OpenCode 地址/,
  );
});

test('a new local conversation captures the initial directory', () => {
  assert.deepEqual(
    resolveSessionBinding(undefined, 'http://127.0.0.1:4096', '/projects/alpha'),
    { directory: '/projects/alpha', endpoint: 'http://127.0.0.1:4096' },
  );
});
