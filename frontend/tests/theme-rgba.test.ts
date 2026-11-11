import assert from 'node:assert/strict';
import test from 'node:test';
import { compareRgba } from '../e2e/themeRgba.ts';

const image = () => ({ width: 2, height: 2, pixels: new Uint8Array(16) });
const region = { x: 0, y: 0, width: 1, height: 1 };

test('RGBA comparison accepts equal images and distinguishes changes inside and outside frozen R', () => {
  const before = image(); const after = image();
  assert.deepEqual(compareRgba(before, after, region, region), { inside: 0, outside: 0, maxDeltaOutside: 0 });
  after.pixels[0] = 255;
  assert.deepEqual(compareRgba(before, after, region, region), { inside: 1, outside: 0, maxDeltaOutside: 0 });
  after.pixels[15] = 1;
  assert.deepEqual(compareRgba(before, after, region, region), { inside: 1, outside: 1, maxDeltaOutside: 1 });
  assert.equal(compareRgba(before, after, null, null).outside, 2);
});

test('RGBA comparison rejects changed masks, invalid geometry and dimensions instead of tolerating differences', () => {
  assert.throws(() => compareRgba(image(), image(), { ...region, width: 2 }, region), /region/i);
  assert.throws(() => compareRgba(image(), image(), null, region), /region/i);
  assert.throws(() => compareRgba(image(), { ...image(), width: 1 }, region, region), /dimensions/i);
  assert.throws(() => compareRgba(image(), image(), { ...region, x: -1 }, { ...region, x: -1 }), /region/i);
  assert.throws(() => compareRgba(image(), image(), { ...region, width: 3 }, { ...region, width: 3 }), /region/i);
  assert.throws(() => compareRgba({ ...image(), pixels: new Uint8Array(0) }, image(), null, null), /dimensions/i);
});
