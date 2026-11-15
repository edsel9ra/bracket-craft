import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import test from 'node:test';

import { catalogParity, extractUsedKeys } from '../app/utils/i18nCatalog.ts';

const appDir = new URL('../app/', import.meta.url);
const translationsSource = readFileSync(new URL('../app/composables/useI18n.ts', import.meta.url), 'utf8');
const englishStart = translationsSource.indexOf('\n  en: {');
assert.ok(englishStart > 0, 'the English catalog is missing');
const spanish = translationsSource.slice(0, englishStart);
const english = translationsSource.slice(englishStart);

const LIVE_FILES = [
  'composables/useMatchOperation.ts',
  'utils/matchLiveEditor.ts',
  'utils/matchLiveLocalDraft.ts',
  'utils/matchLiveCapture.ts',
  'utils/matchLiveEdit.ts',
  'utils/matchLiveAccess.ts',
  'utils/matchLiveClock.ts',
  'utils/matchLiveTransitions.ts',
  'utils/matchLiveReview.ts',
  'utils/matchLiveCloseLive.ts',
  'utils/matchLiveContext.ts',
  'utils/matchLiveClose.ts',
];

function liveSources(): { name: string; source: string }[] {
  return LIVE_FILES.map((name) => ({
    name,
    source: readFileSync(new URL(`../app/${name}`, import.meta.url), 'utf8'),
  }));
}

function keysIn(slice: string): Set<string> {
  const found = new Set<string>();
  for (const match of slice.matchAll(/'((?:[^'\\]|\\.)*)':\s*'/g)) {
    found.add(match[1]!);
  }
  return found;
}

const spanishKeys = keysIn(spanish);
const englishKeys = keysIn(english);

test('cada clave live.* usada por los controles F1 existe una vez en ES y EN', () => {
  const used = extractUsedKeys(liveSources());
  const liveUsed = [...used.keys()].filter((key) => key.startsWith('live.'));
  // `t(\`live.transition.${kind}.*\`)` se resuelve por plantilla: sus claves se
  // verifican en el test de diálogos más abajo, no por extracción literal.
  assert.ok(liveUsed.length >= 9, `expected the live controls to use >=9 keys, got ${liveUsed.length}`);
  for (const key of liveUsed) {
    assert.equal(
      spanish.split(`'${key}':`).length - 1,
      1,
      `${key} is not declared exactly once in Spanish`,
    );
    assert.equal(
      english.split(`'${key}':`).length - 1,
      1,
      `${key} is not declared exactly once in English`,
    );
  }
});

test('los catálogos live.* tienen paridad ES/EN completa', () => {
  const parity = catalogParity(
    [...spanishKeys].filter((k) => k.startsWith('live.')),
    [...englishKeys].filter((k) => k.startsWith('live.')),
  );
  assert.deepEqual(parity.onlySpanish, []);
  assert.deepEqual(parity.onlyEnglish, []);
});

test('ningún control F1 usa diálogos nativos ni literales de interfaz', () => {
  for (const { name, source } of liveSources()) {
    assert.equal(
      /window\.(confirm|alert|prompt)/.test(source),
      false,
      `${name} uses a native dialog`,
    );
    // Nada de globales implícitos: toda confirmación pasa por useConfirm(t(key)).
    assert.equal(
      /(?<![.\w])alert\s*\(|(?<![.\w])prompt\s*\(/.test(source),
      false,
      `${name} calls alert()/prompt()`,
    );
  }
});

test('todas las confirmaciones F1 usan claves i18n (título, mensaje y acción)', () => {
  const operation = readFileSync(new URL('../app/composables/useMatchOperation.ts', import.meta.url), 'utf8');
  const confirmCalls = operation.match(/t\(`live\.transition\..+`\)|t\('live\.[^']+'\)/g) ?? [];
  for (const key of ['live.localDraft', 'live.editCorrect', 'live.editRemove', 'live.transition.start', 'live.transition.suspend', 'live.transition.resume', 'live.closeConfirm']) {
    assert.ok(
      spanishKeys.has(`${key}.title`) && spanishKeys.has(`${key}.message`),
      `${key} is missing its dialog keys in Spanish`,
    );
    assert.ok(
      englishKeys.has(`${key}.title`) && englishKeys.has(`${key}.message`),
      `${key} is missing its dialog keys in English`,
    );
  }
  assert.ok(confirmCalls.length >= 4, 'expected the live confirmations to resolve i18n keys');
});

test('el estado F1 se presenta por modo/capacidad, nunca solo por color', () => {
  const access = readFileSync(new URL('../app/utils/matchLiveAccess.ts', import.meta.url), 'utf8');
  assert.match(access, /LiveViewMode = 'hidden' \| 'reader' \| 'operator' \| 'closer'/);
  const clock = readFileSync(new URL('../app/utils/matchLiveClock.ts', import.meta.url), 'utf8');
  // El reloj desactualizado se anuncia como `stale` (texto/estado), no por color.
  assert.match(clock, /stale/);
  const editor = readFileSync(new URL('../app/utils/matchLiveEditor.ts', import.meta.url), 'utf8');
  assert.match(editor, /pending/);
});
