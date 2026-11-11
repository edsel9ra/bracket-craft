import { PALETTES } from './designTokens.ts';

export type ThemePreference = 'dark' | 'light' | 'system';

export const THEME_COOKIE_NAME = 'bc_theme';
export const THEME_COOKIE_OPTIONS = { path: '/', maxAge: 31536000, sameSite: 'lax' } as const;

export function isThemePreference(value: unknown): value is ThemePreference {
  return value === 'dark' || value === 'light' || value === 'system';
}

export function normalizeTheme(value: unknown): ThemePreference {
  return isThemePreference(value) ? value : 'dark';
}

export function describeTheme(value: unknown) {
  const preference = normalizeTheme(value);
  const colors = { dark: PALETTES.dark.canvas, light: PALETTES.light.canvas };
  const meta = preference === 'system'
    ? (['dark', 'light'] as const).map(theme => ({
        name: 'theme-color',
        content: colors[theme],
        media: `(prefers-color-scheme: ${theme})`,
      }))
    : [{ name: 'theme-color', content: colors[preference] }];
  return { htmlAttrs: { 'data-theme': preference }, meta };
}
