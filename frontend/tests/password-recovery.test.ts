import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  PASSWORD_ERROR_CODES,
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  confirmationError,
  emailError,
  newPasswordError,
  passwordErrorCode,
  passwordErrorKey,
  resetTokenFromHash,
  urlWithoutFragment,
} from '../app/utils/passwordRecovery.ts';
import { catalogKeys } from '../app/utils/i18nCatalog.ts';

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');
const I18N = read('../app/composables/useI18n.ts');
const ENGLISH_START = I18N.indexOf('\n  en: {');
const SPANISH_KEYS = new Set(catalogKeys(I18N.slice(0, ENGLISH_START)));
const ENGLISH_KEYS = new Set(catalogKeys(I18N.slice(ENGLISH_START)));
const FORGOT = read('../app/pages/password/forgot.vue');
const RESET = read('../app/pages/password/reset.vue');
const CHANGE = read('../app/pages/account/password.vue');
const LOGIN = read('../app/pages/login.vue');
const SHELL = read('../app/components/WorkspaceShell.vue');
const COMPOSABLE = read('../app/composables/usePasswordAccount.ts');
const TOKEN = 'fragmento-de-prueba-'.repeat(2);

test('039 RF-005: el token se lee solo del fragmento y con forma base64url', () => {
  assert.equal(resetTokenFromHash(`#${TOKEN}`), TOKEN);
  assert.equal(resetTokenFromHash(TOKEN), TOKEN);
  for (const bad of ['', '#', '#a b', '#a/b', '#a?b=1', `#${'a'.repeat(129)}`, null, undefined, 3]) {
    assert.equal(resetTokenFromHash(bad as never), null, String(bad));
  }
  assert.equal(urlWithoutFragment('/password/reset', '?x=1'), '/password/reset?x=1');
});

test('039 RF-005: la pantalla retira el fragmento del historial al leerlo', () => {
  assert.match(RESET, /resetTokenFromHash\(window\.location\.hash\)/);
  assert.match(RESET, /window\.history\.replaceState\(/);
  assert.doesNotMatch(RESET, /route\.(hash|query|params)/);
});

test('039 RF-009: validación local de la política de contraseña', () => {
  assert.equal(PASSWORD_MIN_LENGTH, 8);
  assert.equal(PASSWORD_MAX_LENGTH, 128);
  assert.deepEqual(newPasswordError(''), { key: 'validation.required' });
  assert.deepEqual(newPasswordError('1234567'), { key: 'validation.minLength', params: { min: 8 } });
  assert.equal(newPasswordError('12345678'), null);
  assert.equal(newPasswordError('a'.repeat(128)), null);
  assert.deepEqual(newPasswordError('a'.repeat(129)), { key: 'validation.maxLength', params: { max: 128 } });
  assert.equal(newPasswordError('😀'.repeat(128)), null);
  assert.deepEqual(newPasswordError('😀'.repeat(129)), { key: 'validation.maxLength', params: { max: 128 } });
  assert.deepEqual(newPasswordError('😀'.repeat(7)), { key: 'validation.minLength', params: { min: 8 } });
  for (const page of ['app/pages/password/reset.vue', 'app/pages/account/password.vue']) {
    assert.doesNotMatch(read(`../${page}`), /maxlength/, `${page} no trunca en unidades UTF-16`);
  }
  assert.deepEqual(confirmationError('secret-pass', ''), { key: 'validation.required' });
  assert.deepEqual(confirmationError('secret-pass', 'secret-pas'), { key: 'password.error.mismatch' });
  assert.equal(confirmationError('secret-pass', 'secret-pass'), null);
  assert.deepEqual(emailError(' '), { key: 'validation.required' });
  assert.deepEqual(emailError('nadia@'), { key: 'validation.email' });
  assert.equal(emailError(' Nadia@Example.com '), null);
});

test('039: catálogo cerrado de errores con mensaje ES/EN', () => {
  assert.deepEqual([...PASSWORD_ERROR_CODES], [
    'PASSWORD_RESET_INVALID',
    'PASSWORD_REUSED',
    'CURRENT_PASSWORD_INVALID',
    'PASSWORD_NOT_SET',
    'RATE_LIMITED',
    'UNAVAILABLE',
  ]);
  assert.equal(passwordErrorCode({ statusCode: 429, data: { detail: 'Demasiadas solicitudes' } }), 'RATE_LIMITED');
  assert.equal(passwordErrorCode({ status: 503 }), 'UNAVAILABLE');
  assert.equal(passwordErrorCode({ statusCode: 400, data: { detail: 'PASSWORD_RESET_INVALID' } }), 'PASSWORD_RESET_INVALID');
  assert.equal(passwordErrorCode({ statusCode: 409, data: { detail: 'PASSWORD_NOT_SET' } }), 'PASSWORD_NOT_SET');
  assert.equal(passwordErrorCode({ statusCode: 400, data: { detail: 'otro' } }), null);
  assert.equal(passwordErrorCode(null), null);
  assert.equal(passwordErrorKey({ statusCode: 422, data: { detail: [] } }), 'password.error.unknown');
  const keys = [
    ...PASSWORD_ERROR_CODES.map((code) => `password.error.${code}`),
    ...[...I18N.slice(0, ENGLISH_START).matchAll(/t\('(password\.[A-Za-z.]+)'/g)].map((match) => match[1]),
    ...[FORGOT, RESET, CHANGE, LOGIN, SHELL].flatMap((source) => [...source.matchAll(/t\('(password\.[A-Za-z_.]+)'/g)].map((match) => match[1])),
    'password.error.unknown',
    'password.error.mismatch',
  ];
  for (const key of new Set(keys)) {
    assert.ok(SPANISH_KEYS.has(key), `missing Spanish key ${key}`);
    assert.ok(ENGLISH_KEYS.has(key), `missing English key ${key}`);
  }
});

test('039 RF-001: la recuperación muestra siempre la misma confirmación genérica', () => {
  assert.match(FORGOT, /await forgot\(email\.value\);\s*\/\/ RF-001[^\n]*\n\s*sent\.value = true;/);
  assert.match(FORGOT, /t\('password\.forgot\.sent'\)/);
  assert.match(FORGOT, /sentRef\.value\?\.focus\(\)/);
  assert.match(FORGOT, /failureRef\.value\?\.focus\(\)/);
});

test('039 RF-004/RF-013: el éxito del enlace cierra la sesión local y lleva al login con aviso', () => {
  assert.match(RESET, /auth\.clearSession\(\);\s*await navigateTo\(\{ path: '\/login', query: \{ notice: 'password-reset' \} \}\)/);
  assert.match(RESET, /to="\/password\/forgot"/);
  assert.match(LOGIN, /route\.query\.notice === 'password-reset'/);
  assert.match(LOGIN, /<NuxtLink v-if="!isRegister" to="\/password\/forgot"/);
});

test('039 RF-006/RF-007/DA-1: el cambio exige sesión, la actual y avisa a las cuentas solo-Google', () => {
  assert.match(CHANGE, /definePageMeta\(\{ middleware: \['session'\] \}\)/);
  assert.match(CHANGE, /v-else-if="!loading && !hasLocalPassword"[^>]*>\s*\{\{ t\('password\.change\.googleOnly'\) \}\}/);
  assert.match(CHANGE, /code === 'CURRENT_PASSWORD_INVALID'[\s\S]*?getElementById\('password-change-current'\)\?\.focus\(\)/);
  assert.match(CHANGE, /autocomplete="current-password"/);
  assert.match(CHANGE, /t\('password\.change\.success'\)/);
});

test('039 RF-013: entrada del menú de cuenta en escritorio y móvil', () => {
  assert.match(SHELL, /<NuxtLink to="\/account\/password" role="menuitem" @click="accountMenuOpen = false">\{\{ t\('password\.change\.title'\) \}\}<\/NuxtLink>/);
  assert.match(SHELL, /<NuxtLink to="\/account\/password" class="workspace-mobile-account-link">\{\{ t\('password\.change\.title'\) \}\}<\/NuxtLink>/);
});

test('039: las cuatro llamadas pasan por useApi con los cuerpos estrictos', () => {
  assert.match(COMPOSABLE, /const \{ request \} = useApi\(\);/);
  assert.match(COMPOSABLE, /'\/auth\/password\/forgot', \{ method: 'POST', body: \{ email: email\.trim\(\) \} \}/);
  assert.match(COMPOSABLE, /'\/auth\/password\/reset', \{ method: 'POST', body: \{ token, new_password: newPassword \} \}/);
  assert.match(COMPOSABLE, /request<\{ has_password: boolean \}>\('\/auth\/password'\)/);
  assert.match(COMPOSABLE, /body: \{ current_password: currentPassword, new_password: newPassword \}/);
  assert.doesNotMatch(COMPOSABLE + FORGOT + RESET + CHANGE, /\$fetch|console\./);
});
