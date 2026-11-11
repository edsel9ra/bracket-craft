import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { compareRgba, type Region } from './themeRgba.ts';

test('@visual RGBA exacto fuera de las regiones congeladas', async ({ page }, info) => {
  const path = process.env.THEME_RGBA_MANIFEST;
  const digest = process.env.THEME_RGBA_SHA256;
  expect(path, 'Provide THEME_RGBA_MANIFEST and its previously recorded THEME_RGBA_SHA256').toBeTruthy();
  const raw = readFileSync(path!);
  expect(createHash('sha256').update(raw).digest('hex')).toBe(digest);
  const cases = JSON.parse(raw.toString()) as { key: string; before: string; after: string; beforeSha256: string; afterSha256: string; region: Region | null; frozen: Region | null }[];
  expect(cases.length).toBeGreaterThan(0);
  const results = [];
  await page.addScriptTag({ content: `window.compareThemeRgba = (${compareRgba.toString()});` });
  for (const item of cases) {
    const sources = [item.before, item.after].map((file, index) => {
      const bytes = readFileSync(file);
      expect(createHash('sha256').update(bytes).digest('hex'), file).toBe(index === 0 ? item.beforeSha256 : item.afterSha256);
      return `data:image/png;base64,${bytes.toString('base64')}`;
    });
    const result = await page.evaluate(async ({ sources, region, frozen }) => {
      const images = await Promise.all(sources.map(async (source) => {
        const image = new Image(); image.src = source; await image.decode();
        const canvas = document.createElement('canvas'); canvas.width = image.width; canvas.height = image.height;
        const ctx = canvas.getContext('2d', { willReadFrequently: true })!; ctx.drawImage(image, 0, 0);
        return { width: image.width, height: image.height, pixels: ctx.getImageData(0, 0, image.width, image.height).data };
      }));
      return (window as unknown as { compareThemeRgba: typeof compareRgba }).compareThemeRgba(images[0]!, images[1]!, region, frozen);
    }, { sources, region: item.region, frozen: item.frozen });
    results.push({ key: item.key, ...result }); console.log(JSON.stringify({ key: item.key, ...result })); expect(result.outside, item.key).toBe(0);
  }
  await info.attach('rgba-results', { body: JSON.stringify(results), contentType: 'application/json' });
});
