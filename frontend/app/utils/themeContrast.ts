import { PALETTE_LIGHT as palette, ISLAND_PALETTES, contrastRatio } from './designTokens.ts';

export function compositeColor(foreground: string, background: string, alpha: number): string {
  contrastRatio(foreground, background);
  if (!Number.isFinite(alpha) || alpha < 0 || alpha > 1) throw new RangeError('Expected alpha between zero and one');
  return '#' + [1, 3, 5].map(offset => Math.round(
    parseInt(foreground.slice(offset, offset + 2), 16) * alpha
    + parseInt(background.slice(offset, offset + 2), 16) * (1 - alpha),
  ).toString(16).padStart(2, '0')).join('');
}

function lightContrastPairs() {
  const pairs: { id: number; label: string; foreground: string; background: string; minimum: number }[] = [];
  const backgrounds = ['canvas', 'canvas-raised', 'surface', 'surface-raised', 'surface-bright'] as const;
  const texts = ['ink', 'muted', 'accent', 'danger', 'warning', 'success', 'home', 'away'] as const;
  function add(label: string, foreground: string, background: string, minimum = 4.5) {
    pairs.push({ id: pairs.length + 1, label, foreground, background, minimum });
  }
  for (const foreground of [...texts, 'line', 'danger-border'] as const) {
    for (const background of backgrounds) add(`${foreground}/${background}`, palette[foreground], palette[background], texts.includes(foreground as typeof texts[number]) ? 4.5 : 3);
  }
  for (const background of ['accent', 'danger', 'warning', 'success', 'home', 'away'] as const) add(`accent-ink/${background}`, palette['accent-ink'], palette[background]);
  for (const background of ['pitch-grass', 'pitch-stripe', 'pitch-player'] as const) {
    for (const foreground of ['ink', 'accent', 'warning'] as const) add(`island.${foreground}/${background}`, ISLAND_PALETTES.light[foreground], palette[background]);
  }
  for (const background of ['pitch-grass', 'pitch-stripe'] as const) add(`pitch-line/${background}`, palette['pitch-line'], palette[background], 3);
  for (const background of backgrounds) {
    add(`avatar-ink/highlight6%/${background}`, palette['avatar-ink'], compositeColor(palette.highlight, palette[background], 0.06));
    for (const alpha of [0.08, 0.10]) {
      for (const foreground of texts) add(`${foreground}/accent${alpha * 100}%/${background}`, palette[foreground], compositeColor(palette.accent, palette[background], alpha));
    }
  }
  for (const background of ['pitch-grass', 'pitch-stripe'] as const) {
    for (const alpha of [0.55, 0.62, 0.85]) add(`pitch-line${alpha * 100}%/${background}`, compositeColor(palette['pitch-line'], palette[background], alpha), palette[background], 3);
  }
  return pairs;
}

export const LIGHT_CONTRAST_PAIRS = lightContrastPairs();
