import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildNativeLauncherRequest,
  nativeLauncherTimeout,
  normalizeNativeLauncherError,
} from '../public/native-launcher-protocol.js';

test('launch request only forwards the fixed allowlist', () => {
  const request = buildNativeLauncherRequest({
    type: 'EIDO_OPENCODE_LAUNCH',
    workspace: '/Users/test/project',
    preferredPort: 4096,
    username: 'opencode',
    password: 'secret',
    command: 'rm -rf /',
    env: { TOKEN: 'nope' },
  });
  assert.deepEqual(request, {
    protocol: 1,
    command: 'launch',
    workspace: '/Users/test/project',
    hostname: '127.0.0.1',
    preferredPort: 4096,
    username: 'opencode',
    password: 'secret',
    allowPortFallback: true,
  });
});

test('rejects invalid ports and non-loopback status endpoints', () => {
  assert.throws(() => buildNativeLauncherRequest({
    type: 'EIDO_OPENCODE_LAUNCH', workspace: '/tmp/project', preferredPort: 80,
  }), /preferredPort/);
  assert.throws(() => buildNativeLauncherRequest({
    type: 'EIDO_OPENCODE_STATUS', endpoint: 'http://192.168.1.2:4096',
  }), /回环地址/);
});

test('maps Chrome host errors to stable error codes', () => {
  assert.equal(
    normalizeNativeLauncherError(new Error('Specified native messaging host not found.')).code,
    'NATIVE_HOST_NOT_FOUND'
  );
  assert.deepEqual(
    normalizeNativeLauncherError({ message: 'Specified native messaging host not found.' }),
    {
      ok: false,
      code: 'NATIVE_HOST_NOT_FOUND',
      message: 'Specified native messaging host not found.',
    }
  );
});

test('allows interactive directory selection more time than native probes', () => {
  assert.equal(nativeLauncherTimeout('ping'), 10000);
  assert.equal(nativeLauncherTimeout('launch'), 45000);
  assert.equal(nativeLauncherTimeout('select_directory'), 5 * 60 * 1000);
});
