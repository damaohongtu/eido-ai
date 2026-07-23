import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const manifest = JSON.parse(
  readFileSync(new URL('../public/manifest.json', import.meta.url), 'utf8')
);
const previewHost = readFileSync(
  new URL('../public/file-preview/index.html', import.meta.url),
  'utf8'
);

function parseDirectives(policy) {
  return new Map(
    policy
      .split(';')
      .map((directive) => directive.trim())
      .filter(Boolean)
      .map((directive) => {
        const [name, ...values] = directive.split(/\s+/);
        return [name, values];
      })
  );
}

test('local HTML preview grants only the trusted loader script capability', () => {
  assert.match(previewHost, /sandbox="allow-scripts"/);
  assert.doesNotMatch(
    previewHost,
    /allow-(?:same-origin|forms|modals|popups|downloads|top-navigation)/
  );
  assert.match(previewHost, /referrerpolicy="no-referrer"/);
});

test('sandbox CSP blocks report scripts, network, forms and nested content', () => {
  const policy = manifest.content_security_policy.sandbox;
  const directives = parseDirectives(policy);

  assert.deepEqual(directives.get('sandbox'), ['allow-scripts']);
  assert.deepEqual(directives.get('default-src'), ["'none'"]);
  assert.deepEqual(directives.get('script-src'), ["'self'"]);
  assert.deepEqual(directives.get('connect-src'), ["'none'"]);
  assert.deepEqual(directives.get('form-action'), ["'none'"]);
  assert.deepEqual(directives.get('object-src'), ["'none'"]);
  assert.deepEqual(directives.get('frame-src'), ["'none'"]);
  assert.deepEqual(directives.get('child-src'), ["'none'"]);
  assert.deepEqual(directives.get('worker-src'), ["'none'"]);
  assert.deepEqual(directives.get('base-uri'), ["'none'"]);
  assert.equal(policy.includes('https:'), false);
  assert.equal(policy.includes("'unsafe-eval'"), false);
  assert.equal(directives.get('script-src').includes("'unsafe-inline'"), false);
});
