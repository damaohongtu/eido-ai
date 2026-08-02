import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  renameSync,
  rmSync,
} from 'node:fs';
import { spawnSync } from 'node:child_process';
import { createHash, createPublicKey } from 'node:crypto';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const projectDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const privateKey = process.env.EIDO_EXTENSION_PRIVATE_KEY;
const updateUrl = process.env.EIDO_EXTENSION_UPDATE_URL;
const chromeBinary = process.env.CHROME_BINARY
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const releaseDir = path.resolve(
  projectDir,
  process.env.EIDO_EXTENSION_RELEASE_DIR || 'release',
);

if (!privateKey) throw new Error('EIDO_EXTENSION_PRIVATE_KEY is required');
if (!updateUrl) throw new Error('EIDO_EXTENSION_UPDATE_URL is required');
if (!existsSync(privateKey)) throw new Error(`Private key not found: ${privateKey}`);
if (!existsSync(chromeBinary)) throw new Error(`Chrome binary not found: ${chromeBinary}`);

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { stdio: 'inherit', ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${path.basename(command)} exited with status ${result.status ?? 'unknown'}`);
  }
}

function prepareChromeKey(sourcePath) {
  const header = readFileSync(sourcePath, 'utf8').split(/\r?\n/, 1)[0];
  if (header === '-----BEGIN PRIVATE KEY-----') {
    return { keyPath: path.resolve(sourcePath), cleanup: () => undefined };
  }
  if (header !== '-----BEGIN RSA PRIVATE KEY-----') {
    throw new Error('Private key must be an unencrypted PKCS#1 or PKCS#8 PEM RSA key');
  }

  const temporaryDirectory = mkdtempSync(path.join(tmpdir(), 'eido-extension-key-'));
  const convertedPath = path.join(temporaryDirectory, 'key.pk8.pem');
  run('openssl', [
    'pkcs8', '-topk8', '-nocrypt', '-in', path.resolve(sourcePath), '-out', convertedPath,
  ]);
  return {
    keyPath: convertedPath,
    cleanup: () => rmSync(temporaryDirectory, { recursive: true, force: true }),
  };
}

function deriveExtensionId(sourcePath) {
  const publicKey = createPublicKey(readFileSync(sourcePath)).export({
    type: 'spki',
    format: 'der',
  });
  const idBytes = createHash('sha256').update(publicKey).digest().subarray(0, 16);
  return [...idBytes]
    .flatMap((byte) => [byte >> 4, byte & 0x0f])
    .map((nibble) => String.fromCharCode('a'.charCodeAt(0) + nibble))
    .join('');
}

const preparedKey = prepareChromeKey(privateKey);
try {
  run('npm', ['run', 'build:release'], {
    cwd: projectDir,
    env: { ...process.env, EIDO_EXTENSION_UPDATE_URL: updateUrl },
  });

  const distDir = path.join(projectDir, 'dist');
  const chromeOutput = `${distDir}.crx`;
  rmSync(chromeOutput, { force: true });
  run(
    chromeBinary,
    [`--pack-extension=${distDir}`, `--pack-extension-key=${preparedKey.keyPath}`],
    { cwd: projectDir },
  );
  if (!existsSync(chromeOutput)) {
    throw new Error(`Chrome did not create the expected CRX: ${chromeOutput}`);
  }

  const manifest = JSON.parse(readFileSync(path.join(distDir, 'manifest.json'), 'utf8'));
  mkdirSync(releaseDir, { recursive: true });
  const target = path.join(releaseDir, `eido-extension-${manifest.version}.crx`);
  rmSync(target, { force: true });
  renameSync(chromeOutput, target);
  process.stdout.write(`Created ${target}\n`);
  process.stdout.write(`Extension ID: ${deriveExtensionId(privateKey)}\n`);
} finally {
  preparedKey.cleanup();
}
