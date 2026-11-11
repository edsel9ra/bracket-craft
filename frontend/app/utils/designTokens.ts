export const TEXT_SIZES = {
  '2xs': '0.6875rem',
  xs: '0.75rem',
  sm: '0.8125rem',
  md: '0.875rem',
  base: '1rem',
  lg: '1.25rem',
  xl: 'clamp(1.75rem, 4vw, 2.75rem)',
  display: 'clamp(2.5rem, 7vw, 6.5rem)',
} as const;
export const TEXT_LINE_HEIGHTS = {
  '2xs': 1.4, xs: 1.4, sm: 1.5, md: 1.5, base: 1.5, lg: 1.3, xl: 1.1, display: 1,
} as const;
export const TEXT_WEIGHTS = {
  '2xs': 400, xs: 400, sm: 400, md: 400, base: 400, lg: 700, xl: 800, display: 900,
} as const;
export const SPACING = {
  1: 4, 2: 8, 3: 12, 4: 16, 5: 20, 6: 24, 7: 32, 8: 48, 9: 64, 10: 80,
} as const;
export const RADII = {
  sm: 8, md: 12, lg: 20, xl: 28, pill: 999,
} as const;
export const PALETTE = {
  ink: '#f4f0e7',
  muted: '#a6aa9f',
  surface: '#151814',
  'surface-raised': '#20251e',
  'surface-bright': '#293325',
  line: '#3b4538',
  accent: '#d4f36a',
  'accent-ink': '#17200f',
  danger: '#ffb0a8',
  warning: '#ffcb7a',
  success: '#d4f36a',
  home: '#d4f36a',
  away: '#ffcb7a',
  canvas: '#0c0f0c',
  'canvas-raised': '#111611',
  shadow: '#000000',
  highlight: '#ffffff',
  'pitch-grass': '#315b35',
  'pitch-stripe': '#38673b',
  'pitch-line': '#ecffce',
  'pitch-player': '#172218',
  'avatar-ink': '#f5f7fb',
  'danger-border': '#a45b5b',
} as const;
export const FONTS = {
  sans: '"Archivo", "Archivo Fallback", Arial, sans-serif',
  display: '"Archivo", "Archivo Fallback", Arial, sans-serif',
  mono: 'ui-monospace, SFMono-Regular, Consolas, monospace',
} as const;
export const BREAKPOINTS = { sm: 480, md: 760, lg: 1000, xl: 1280 } as const;

export const CSS_TOKENS: Record<string, string> = Object.fromEntries([
  ...Object.entries(TEXT_SIZES).map(([key, value]) => [`text-${key}`, value]),
  ...Object.entries(TEXT_LINE_HEIGHTS).map(([key, value]) => [`leading-${key}`, String(value)]),
  ...Object.entries(TEXT_WEIGHTS).map(([key, value]) => [`weight-${key}`, String(value)]),
  ...Object.entries(SPACING).map(([key, value]) => [`space-${key}`, `${value}px`]),
  ...Object.entries(RADII).map(([key, value]) => [`radius-${key}`, `${value}px`]),
  ...Object.entries(PALETTE).map(([key, value]) => [`color-${key}`, value]),
  ...Object.entries(FONTS).map(([key, value]) => [`font-${key}`, value]),
  ...Object.entries(BREAKPOINTS).map(([key, value]) => [`breakpoint-${key}`, `${value}px`]),
]);

type ColorName = keyof typeof PALETTE;
export const CONTRAST_PAIRS: { foreground: ColorName; background: ColorName; minimum: number }[] = [
  ...(['surface', 'surface-raised', 'surface-bright'] as const).flatMap((background) =>
    (['ink', 'muted', 'accent', 'danger', 'warning', 'success', 'home', 'away'] as const)
      .map((foreground) => ({ foreground, background, minimum: 4.5 }))),
  ...(['accent', 'danger', 'warning', 'success'] as const).map((background) =>
    ({ foreground: 'accent-ink' as const, background, minimum: 4.5 })),
  { foreground: 'accent', background: 'surface', minimum: 3 },
];

export function contrastRatio(foreground: string, background: string): number {
  function luminance(hex: string): number {
    if (!/^#[0-9a-f]{6}$/i.test(hex)) throw new TypeError('Expected a six-digit hex color');
    const channels = [1, 3, 5].map((offset) => {
      const value = parseInt(hex.slice(offset, offset + 2), 16) / 255;
      return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
    });
    return channels[0]! * 0.2126 + channels[1]! * 0.7152 + channels[2]! * 0.0722;
  }
  const first = luminance(foreground);
  const second = luminance(background);
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
}

export function nearestStep(value: number, scale: readonly number[]): number {
  if (!Number.isFinite(value) || !scale.length || scale.some((step) => !Number.isFinite(step))) {
    throw new RangeError('Expected a finite value and nonempty finite scale');
  }
  return scale.reduce((best, step) =>
    Math.abs(step - value) < Math.abs(best - value)
      || (Math.abs(step - value) === Math.abs(best - value) && step < best) ? step : best);
}
