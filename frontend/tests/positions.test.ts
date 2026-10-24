import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import test from 'node:test';

import {
  POSITION_CODES,
  POSITION_DEFINITIONS,
  positionKey,
  positionLabel,
  positionSide,
  type PositionSide,
} from '../app/utils/positions.ts';

// RF-027 / RF-028 (POS-1): el apéndice C de la spec 012 fija la tabla de los
// 23 códigos con su etiqueta corta es/en y su lado. El código es el valor
// contractual y no cambia; solo se localiza lo que se muestra. La fuente única
// aporta la clave i18n (`positions.<CODE>`), nunca el texto: los catálogos viven
// solo en `useI18n.ts`. Una posición desconocida (o sin clave) se muestra tal
// cual, nunca vacía ni inventada.

interface ExpectedPosition {
  es: string;
  en: string;
  side: PositionSide;
}

const EXPECTED: Record<string, ExpectedPosition> = {
  GK: { es: 'Portero', en: 'Goalkeeper', side: null },
  CB: { es: 'Central', en: 'Centre-back', side: null },
  LCB: { es: 'Central izquierdo', en: 'Left centre-back', side: 'left' },
  RCB: { es: 'Central derecho', en: 'Right centre-back', side: 'right' },
  LB: { es: 'Lateral izquierdo', en: 'Left back', side: 'left' },
  RB: { es: 'Lateral derecho', en: 'Right back', side: 'right' },
  LWB: { es: 'Carrilero izquierdo', en: 'Left wing-back', side: 'left' },
  RWB: { es: 'Carrilero derecho', en: 'Right wing-back', side: 'right' },
  CDM_L: { es: 'Pivote izquierdo', en: 'Left defensive midfielder', side: 'left' },
  CDM_R: { es: 'Pivote derecho', en: 'Right defensive midfielder', side: 'right' },
  CM: { es: 'Mediocentro', en: 'Central midfielder', side: null },
  CM_L: { es: 'Mediocentro izquierdo', en: 'Left central midfielder', side: 'left' },
  CM_R: { es: 'Mediocentro derecho', en: 'Right central midfielder', side: 'right' },
  LCM: { es: 'Mediocentro izquierdo', en: 'Left central midfielder', side: 'left' },
  RCM: { es: 'Mediocentro derecho', en: 'Right central midfielder', side: 'right' },
  LM: { es: 'Interior izquierdo', en: 'Left midfielder', side: 'left' },
  RM: { es: 'Interior derecho', en: 'Right midfielder', side: 'right' },
  CAM: { es: 'Mediapunta', en: 'Attacking midfielder', side: null },
  LW: { es: 'Extremo izquierdo', en: 'Left winger', side: 'left' },
  RW: { es: 'Extremo derecho', en: 'Right winger', side: 'right' },
  ST: { es: 'Delantero centro', en: 'Centre-forward', side: null },
  ST_L: { es: 'Delantero izquierdo', en: 'Left forward', side: 'left' },
  ST_R: { es: 'Delantero derecho', en: 'Right forward', side: 'right' },
};

const NO_SIDE_CODES = ['GK', 'CB', 'CM', 'CAM', 'ST'];

const POSITIONS_SOURCE = readFileSync(
  new URL('../app/utils/positions.ts', import.meta.url),
  'utf8',
);
const TRANSLATIONS_SOURCE = readFileSync(
  new URL('../app/composables/useI18n.ts', import.meta.url),
  'utf8',
);

const APP_DIR = new URL('../app/', import.meta.url);
const APP_FILES = (readdirSync(APP_DIR, { recursive: true }) as string[])
  .filter((file) => file.endsWith('.ts') || file.endsWith('.vue'))
  .map((file) => ({
    name: file.replaceAll('\\', '/'),
    source: readFileSync(new URL(file.replaceAll('\\', '/'), APP_DIR), 'utf8'),
  }))
  .filter((entry) => !entry.name.startsWith('.'));

function appSource(relativePath: string): string {
  return readFileSync(new URL(relativePath, APP_DIR), 'utf8');
}

function catalogSlices(): { spanish: string; english: string } {
  const englishStart = TRANSLATIONS_SOURCE.indexOf('\n  en: {');
  assert.ok(englishStart > 0, 'the English catalog is missing');
  return {
    spanish: TRANSLATIONS_SOURCE.slice(0, englishStart),
    english: TRANSLATIONS_SOURCE.slice(englishStart),
  };
}

function catalogMap(slice: string): Map<string, string> {
  const map = new Map<string, string>();
  const pattern = /'((?:[^'\\]|\\.)*)':\s*'((?:[^'\\]|\\.)*)'/g;
  for (const match of slice.matchAll(pattern)) {
    map.set(match[1]!, match[2]!.replaceAll("\\'", "'"));
  }
  return map;
}

function sideDeclaredByCode(code: string): PositionSide {
  if (code.endsWith('_L') || code.startsWith('L')) return 'left';
  if (code.endsWith('_R') || code.startsWith('R')) return 'right';
  return null;
}

test('declares exactly the 23 codes of the closed formation catalog', () => {
  assert.equal(POSITION_CODES.length, 23, 'the table must have 23 rows');
  assert.equal(new Set(POSITION_CODES).size, 23, 'the codes must be unique');
  assert.deepEqual([...POSITION_CODES].sort(), Object.keys(EXPECTED).sort());
  assert.deepEqual(Object.keys(POSITION_DEFINITIONS).sort(), Object.keys(EXPECTED).sort());
});

test('every code declares a stable i18n key and never a literal label', () => {
  for (const code of POSITION_CODES) {
    const definition = POSITION_DEFINITIONS[code];
    assert.ok(definition, `missing definition for ${code}`);
    assert.deepEqual(
      Object.keys(definition).sort(),
      ['key', 'side'],
      `${code} must declare only key and side`,
    );
    assert.equal(definition.key, `positions.${code}`, `${code} has no stable i18n key`);
    assert.equal(positionKey(code), `positions.${code}`, `positionKey(${code}) is wrong`);
  }
});

test('the Spanish catalog has the 23 labels from appendix C', () => {
  const { spanish } = catalogSlices();
  const catalog = catalogMap(spanish);
  for (const code of POSITION_CODES) {
    const key = `positions.${code}`;
    assert.equal(spanish.split(`'${key}':`).length - 1, 1, `${key} is not declared exactly once in Spanish`);
    assert.equal(catalog.get(key), EXPECTED[code]!.es, `wrong Spanish label for ${key}`);
  }
});

test('the English catalog has the same 23 keys with the validated labels', () => {
  const { english } = catalogSlices();
  const catalog = catalogMap(english);
  for (const code of POSITION_CODES) {
    const key = `positions.${code}`;
    assert.equal(english.split(`'${key}':`).length - 1, 1, `${key} is not declared exactly once in English`);
    assert.equal(catalog.get(key), EXPECTED[code]!.en, `wrong English label for ${key}`);
  }
});

test('Spanish and English keep an exact parity for the 23 position keys', () => {
  const { spanish, english } = catalogSlices();
  const spanishKeys = [...catalogMap(spanish).keys()].filter((key) => key.startsWith('positions.'));
  const englishKeys = [...catalogMap(english).keys()].filter((key) => key.startsWith('positions.'));
  const expectedKeys = POSITION_CODES.map((code) => `positions.${code}`);
  assert.deepEqual([...spanishKeys].sort(), [...expectedKeys].sort());
  assert.deepEqual([...englishKeys].sort(), [...expectedKeys].sort());
});

test('declares a side only for the codes that carry one', () => {
  for (const code of POSITION_CODES) {
    const expected = EXPECTED[code]!.side;
    assert.equal(sideDeclaredByCode(code), expected, `${code} side in the code is not the declared one`);
    assert.equal(POSITION_DEFINITIONS[code].side, expected, `${code} declares the wrong side`);
    assert.equal(positionSide(code), expected, `positionSide(${code}) is wrong`);
  }
  const noSide = POSITION_CODES.filter((code) => positionSide(code) === null);
  assert.deepEqual([...noSide].sort(), [...NO_SIDE_CODES].sort());
  assert.equal(positionSide('XYZ'), null);
  assert.equal(positionSide(''), null);
  assert.equal(positionSide(null), null);
});

test('resolves the localized short name through the existing translator', () => {
  const { spanish, english } = catalogSlices();
  const spanishCatalog = catalogMap(spanish);
  const englishCatalog = catalogMap(english);
  const tEs = (key: string): string => spanishCatalog.get(key) ?? key;
  const tEn = (key: string): string => englishCatalog.get(key) ?? key;

  for (const code of POSITION_CODES) {
    assert.equal(positionLabel(code, tEs), EXPECTED[code]!.es, `wrong Spanish label for ${code}`);
    assert.equal(positionLabel(code, tEn), EXPECTED[code]!.en, `wrong English label for ${code}`);
  }
});

test('falls back to the received code when it is unknown or its key is missing', () => {
  const { spanish } = catalogSlices();
  const catalog = catalogMap(spanish);
  const t = (key: string): string => catalog.get(key) ?? key;

  assert.equal(positionLabel('XYZ', t), 'XYZ');
  assert.equal(positionLabel('cdm', t), 'cdm');
  assert.equal(positionLabel('', t), '');
  assert.equal(positionLabel(null, t), '');
  assert.equal(positionLabel(undefined, t), '');
  assert.equal(positionLabel('  ST_L  ', t), 'Delantero izquierdo');
  // `t()` devuelve la clave cuando no existe: la etiqueta cae al código.
  assert.equal(positionLabel('GK', (key) => key), 'GK');
  assert.equal(positionKey('XYZ'), 'XYZ');
  assert.equal(positionKey(''), '');
  assert.equal(positionKey(null), '');
});

test('positions.ts holds keys, never literal labels or a translation table', () => {
  for (const code of POSITION_CODES) {
    for (const label of [EXPECTED[code]!.es, EXPECTED[code]!.en]) {
      for (const quoted of [`'${label}'`, `"${label}"`, `\`${label}\``]) {
        assert.ok(
          !POSITIONS_SOURCE.includes(quoted),
          `positions.ts contains the literal label ${quoted}`,
        );
      }
    }
  }
  assert.doesNotMatch(POSITIONS_SOURCE, /\b(?:es|en)\s*:/, 'positions.ts declares its own translations');
  assert.doesNotMatch(POSITIONS_SOURCE, /POSITION_LABELS/, 'positions.ts still exports label records');
});

test('there is a single label table and no duplicated position labels', () => {
  const formations = appSource('constants/formations.ts');
  assert.doesNotMatch(formations, /positionLabel/, 'constants/formations.ts still formats position labels');
  assert.doesNotMatch(formations, /replace\('_', ' '\)/, 'constants/formations.ts still formats position labels');

  const matchPage = appSource('pages/workspace/matches/[id].vue');
  assert.doesNotMatch(matchPage, /\bfunction\s+positionLabel\b/, 'the match page defines its own position labels');
  assert.doesNotMatch(matchPage, /position\.replace\('_', ' '\)/, 'the match page still formats position codes');
  assert.match(matchPage, /from '~\/utils\/positions'/, 'the match page does not use the single source');
  assert.match(matchPage, /positionLabel\([^)]*,\s*t\)/, 'the match page does not translate through t()');

  for (const component of ['components/public/MatchPitch.vue', 'components/public/PublicLineupModal.vue']) {
    const source = appSource(component);
    assert.match(source, /from '~\/utils\/positions'/, `${component} does not use the single source`);
    assert.match(source, /positionLabel\([^)]*,\s*t\)/, `${component} does not translate through t()`);
  }

  const definition = /\b(?:function|const)\s+positionLabel\b/;
  for (const { name, source } of APP_FILES) {
    if (name === 'utils/positions.ts') continue;
    assert.doesNotMatch(source, definition, `${name} defines a second positionLabel`);
  }

  // Las etiquetas solo pueden vivir en el catálogo es/en de `useI18n.ts`.
  const labels = Object.values(EXPECTED).flatMap((entry) => [entry.es, entry.en]);
  for (const { name, source } of APP_FILES) {
    if (name === 'utils/positions.ts' || name === 'composables/useI18n.ts') continue;
    for (const label of labels) {
      assert.ok(
        !source.includes(`'${label}'`) && !source.includes(`"${label}"`) && !source.includes(`\`${label}\``),
        `${name} duplicates the position label "${label}"`,
      );
    }
  }
});
