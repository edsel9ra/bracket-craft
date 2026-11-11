import assert from 'node:assert/strict';
import test from 'node:test';
import { describeTheme, isThemePreference, normalizeTheme, THEME_COOKIE_NAME, THEME_COOKIE_OPTIONS } from '../app/utils/theme.ts';

test('theme defaults to dark without repairing absent or invalid preferences', () => {
  for (const value of [undefined, null, '', 'LIGHT', 'invalid', {}, [], 0]) {
    assert.equal(normalizeTheme(value), 'dark');
    assert.equal(isThemePreference(value), false);
  }
  for (const value of ['dark', 'light', 'system']) {
    assert.equal(normalizeTheme(value), value);
    assert.equal(isThemePreference(value), true);
  }
});

test('theme metadata resolves explicit themes and leaves system resolution to media', () => {
  for (const [preference, color] of [['dark', '#0c0f0c'], ['light', '#f5f7ef']] as const) {
    const head = describeTheme(preference);
    assert.deepEqual(head.htmlAttrs, { 'data-theme': preference });
    assert.deepEqual(head.meta, [{ name: 'theme-color', content: color }]);
  }
  const head = describeTheme('system');
  assert.deepEqual(head.htmlAttrs, { 'data-theme': 'system' });
  assert.deepEqual(head.meta, [
    { name: 'theme-color', content: '#0c0f0c', media: '(prefers-color-scheme: dark)' },
    { name: 'theme-color', content: '#f5f7ef', media: '(prefers-color-scheme: light)' },
  ]);
  assert.deepEqual(describeTheme(null), describeTheme('dark'));
});

test('theme cookie is optional, site-wide and annual without an identity', () => {
  assert.equal(THEME_COOKIE_NAME, 'bc_theme');
  assert.deepEqual(THEME_COOKIE_OPTIONS, { path: '/', maxAge: 31536000, sameSite: 'lax' });
});
