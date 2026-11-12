export interface Region { x: number; y: number; width: number; height: number }
export interface RgbaImage { width: number; height: number; pixels: Uint8Array | Uint8ClampedArray }

export function compareRgba(before: RgbaImage, after: RgbaImage, region: Region | null, frozen: Region | null) {
  if (before.width !== after.width || before.height !== after.height
    || ![before.width, before.height].every(value => Number.isInteger(value) && value > 0)
    || before.pixels.length !== before.width * before.height * 4 || after.pixels.length !== before.pixels.length) throw new RangeError('Invalid image dimensions');
  if ((region === null) !== (frozen === null)
    || (region && frozen && (['x', 'y', 'width', 'height'] as const).some(key => region[key] !== frozen[key]))) throw new RangeError('Changed frozen region');
  if (region && (![region.x, region.y, region.width, region.height].every(Number.isFinite)
    || region.x < 0 || region.y < 0 || region.width <= 0 || region.height <= 0
    || region.x + region.width > before.width || region.y + region.height > before.height)) throw new RangeError('Invalid region');
  const box = region ? { left: Math.floor(region.x), top: Math.floor(region.y), right: Math.ceil(region.x + region.width), bottom: Math.ceil(region.y + region.height) } : null;
  let inside = 0; let outside = 0; let maxDeltaOutside = 0;
  for (let y = 0; y < before.height; y++) for (let x = 0; x < before.width; x++) {
    const index = (y * before.width + x) * 4;
    let delta = 0;
    for (let channel = 0; channel < 4; channel++) delta = Math.max(delta, Math.abs(before.pixels[index + channel]! - after.pixels[index + channel]!));
    if (!delta) continue;
    if (box && x >= box.left && x < box.right && y >= box.top && y < box.bottom) inside++;
    else { outside++; maxDeltaOutside = Math.max(maxDeltaOutside, delta); }
  }
  return { inside, outside, maxDeltaOutside };
}
