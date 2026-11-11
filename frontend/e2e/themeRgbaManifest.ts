import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { Region } from './themeRgba.ts';

const [before, after, output] = process.argv.slice(2);
if (!before || !after || !output) throw new Error('Usage: themeRgbaManifest.ts before-directory after-directory new-manifest.json');
type Entry = { key: string; region: Region | null };
const baseline = JSON.parse(readFileSync(resolve(before, 'manifest.json'), 'utf8')) as Entry[];
const candidate = JSON.parse(readFileSync(resolve(after, 'manifest.json'), 'utf8')) as Entry[];
if (!baseline.length || baseline.length !== candidate.length || new Set(baseline.map(row => row.key)).size !== baseline.length) throw new Error('Invalid capture manifests');
const cases = baseline.map(row => {
  const match = candidate.find(item => item.key === row.key);
  if (!match) throw new Error(`Missing capture ${row.key}`);
  const beforePath = resolve(before, `${row.key}.png`); const afterPath = resolve(after, `${row.key}.png`);
  return { key: row.key, before: beforePath, after: afterPath,
    beforeSha256: createHash('sha256').update(readFileSync(beforePath)).digest('hex'),
    afterSha256: createHash('sha256').update(readFileSync(afterPath)).digest('hex'),
    region: match.region, frozen: row.region };
});
const raw = JSON.stringify(cases, null, 2);
writeFileSync(output, raw, { flag: 'wx' });
console.log(`THEME_RGBA_SHA256=${createHash('sha256').update(raw).digest('hex')}`);
