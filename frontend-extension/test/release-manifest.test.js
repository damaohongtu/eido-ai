import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { prepareReleaseManifest } from '../scripts/release-manifest.mjs';

const background = readFileSync(new URL('../public/background.js', import.meta.url), 'utf8');


test('release build injects the Chrome update URL into the built manifest', () => {
  const directory = mkdtempSync(path.join(tmpdir(), 'eido-extension-release-'));
  const manifestPath = path.join(directory, 'manifest.json');
  const packagePath = path.join(directory, 'package.json');
  writeFileSync(manifestPath, JSON.stringify({ name: 'Eido', version: '0.1.3' }));
  writeFileSync(packagePath, JSON.stringify({ version: '0.1.3' }));

  prepareReleaseManifest(manifestPath, packagePath, 'https://updates.example.com/updates.xml');

  const result = JSON.parse(readFileSync(manifestPath, 'utf8'));
  assert.equal(result.update_url, 'https://updates.example.com/updates.xml');
});


test('release build allows HTTP update URLs on RFC1918 private IPv4 hosts', () => {
  const directory = mkdtempSync(path.join(tmpdir(), 'eido-extension-release-'));
  const manifestPath = path.join(directory, 'manifest.json');
  const packagePath = path.join(directory, 'package.json');
  writeFileSync(manifestPath, JSON.stringify({ name: 'Eido', version: '0.1.7' }));
  writeFileSync(packagePath, JSON.stringify({ version: '0.1.7' }));

  prepareReleaseManifest(
    manifestPath,
    packagePath,
    'http://192.168.127.32:60088/extensions/eido/update.xml',
  );

  const result = JSON.parse(readFileSync(manifestPath, 'utf8'));
  assert.equal(
    result.update_url,
    'http://192.168.127.32:60088/extensions/eido/update.xml',
  );
});


test('release build rejects insecure remote update URLs and version drift', () => {
  const directory = mkdtempSync(path.join(tmpdir(), 'eido-extension-release-'));
  const manifestPath = path.join(directory, 'manifest.json');
  const packagePath = path.join(directory, 'package.json');
  writeFileSync(manifestPath, JSON.stringify({ version: '0.1.3' }));
  writeFileSync(packagePath, JSON.stringify({ version: '0.1.2' }));

  assert.throws(
    () => prepareReleaseManifest(manifestPath, packagePath, 'http://updates.example.com/updates.xml'),
    /must use HTTPS/,
  );
  assert.throws(
    () => prepareReleaseManifest(manifestPath, packagePath, 'https://updates.example.com/updates.xml'),
    /does not match/,
  );
});


test('downloaded Chrome updates are applied by reloading the extension', () => {
  assert.match(background, /chrome\.runtime\.onUpdateAvailable\.addListener/);
  assert.match(background, /chrome\.runtime\.reload\(\)/);
});
