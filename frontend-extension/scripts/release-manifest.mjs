import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

function isAllowedUpdateUrl(url) {
  const parsed = new URL(url);
  if (parsed.protocol === 'https:') return true;
  if (parsed.protocol !== 'http:') return false;
  if (['127.0.0.1', 'localhost', '[::1]'].includes(parsed.hostname)) return true;

  const octets = parsed.hostname.split('.').map(Number);
  if (octets.length !== 4 || octets.some((octet) => !Number.isInteger(octet) || octet < 0 || octet > 255)) {
    return false;
  }

  return (
    octets[0] === 10 ||
    (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31) ||
    (octets[0] === 192 && octets[1] === 168)
  );
}

export function prepareReleaseManifest(manifestPath, packagePath, updateUrl) {
  if (!updateUrl) {
    throw new Error('EIDO_EXTENSION_UPDATE_URL is required');
  }
  if (!isAllowedUpdateUrl(updateUrl)) {
    throw new Error(
      'EIDO_EXTENSION_UPDATE_URL must use HTTPS, except for loopback or RFC1918 private IPv4 hosts'
    );
  }

  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  const packageJson = JSON.parse(readFileSync(packagePath, 'utf8'));
  if (manifest.version !== packageJson.version) {
    throw new Error(
      `manifest version ${manifest.version} does not match package version ${packageJson.version}`
    );
  }

  manifest.update_url = updateUrl;
  writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
  return manifest;
}

const invokedPath = process.argv[1] ? pathToFileURL(process.argv[1]).href : '';
if (import.meta.url === invokedPath) {
  const manifest = prepareReleaseManifest(
    new URL('../dist/manifest.json', import.meta.url),
    new URL('../package.json', import.meta.url),
    process.env.EIDO_EXTENSION_UPDATE_URL,
  );
  process.stdout.write(
    `Prepared release manifest ${manifest.version} with update URL ${manifest.update_url}\n`
  );
}
