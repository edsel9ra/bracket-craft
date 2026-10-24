import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import test from 'node:test';

import {
  ASSIGNABLE_ROLE_CODES,
  INVITATION_STATUS_LABEL_KEYS,
  MEMBER_STATUS_LABEL_KEYS,
  ROLE_CODES,
  ROLE_DEFINITIONS,
  invitationStatusLabelKey,
  isAssignableRole,
  memberStatusLabelKey,
  roleKey,
} from '../app/utils/labels.ts';
import { POSITION_CODES, positionKey } from '../app/utils/positions.ts';
import {
  catalogKeys,
  catalogParity,
  extractUsedKeys,
  extractVisibleLiterals,
  findMissingKeys,
} from '../app/utils/i18nCatalog.ts';

// RF-025 / RF-026 (R29): los cinco roles de la organización (dueño,
// administrador, operador, árbitro y observador) salen de **una sola fuente**
// que devuelve la clave i18n, nunca el texto. `owner` es conocido y no editable:
// se muestra traducido donde aparece, incluida la tabla de miembros. Un código
// desconocido se muestra tal cual, sin inventar traducción ni dejar el hueco
// vacío. El código es el valor contractual: la autorización y los permisos
// siguen comparando códigos, jamás etiquetas.

interface ExpectedRole {
  es: string;
  en: string;
  assignable: boolean;
}

const EXPECTED_ROLES: Record<string, ExpectedRole> = {
  owner: { es: 'Dueño', en: 'Owner', assignable: false },
  administrator: { es: 'Administrador', en: 'Administrator', assignable: true },
  operator: { es: 'Operador', en: 'Operator', assignable: true },
  referee: { es: 'Árbitro', en: 'Referee', assignable: true },
  viewer: { es: 'Observador', en: 'Viewer', assignable: true },
};

const LABELS_SOURCE = readFileSync(
  new URL('../app/utils/labels.ts', import.meta.url),
  'utf8',
);
const TRANSLATIONS_SOURCE = readFileSync(
  new URL('../app/composables/useI18n.ts', import.meta.url),
  'utf8',
);
const MEMBERS_PAGE = readFileSync(
  new URL('../app/pages/workspace/members.vue', import.meta.url),
  'utf8',
);
const INVITATION_PAGE = readFileSync(
  new URL('../app/pages/invitations/[token].vue', import.meta.url),
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

const VIEW_FILES = APP_FILES.filter((entry) => entry.name.endsWith('.vue'));

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

test('declares exactly the five known organization roles', () => {
  assert.deepEqual([...ROLE_CODES], ['owner', 'administrator', 'operator', 'referee', 'viewer']);
  assert.equal(new Set(ROLE_CODES).size, 5, 'the codes must be unique');
  assert.deepEqual(Object.keys(ROLE_DEFINITIONS).sort(), Object.keys(EXPECTED_ROLES).sort());
});

test('every role declares a stable i18n key and never a literal label', () => {
  for (const code of ROLE_CODES) {
    const definition = ROLE_DEFINITIONS[code];
    assert.ok(definition, `missing definition for ${code}`);
    assert.deepEqual(
      Object.keys(definition).sort(),
      ['assignable', 'key'],
      `${code} must declare only key and assignable`,
    );
    assert.equal(definition.key, `roles.${code}`, `${code} has no stable i18n key`);
    assert.equal(roleKey(code), `roles.${code}`, `roleKey(${code}) is wrong`);
  }

  for (const role of Object.values(EXPECTED_ROLES)) {
    for (const label of [role.es, role.en]) {
      for (const quoted of [`'${label}'`, `"${label}"`, `\`${label}\``]) {
        assert.ok(
          !LABELS_SOURCE.includes(quoted),
          `labels.ts contains the literal label ${quoted}`,
        );
      }
    }
  }
  assert.doesNotMatch(LABELS_SOURCE, /\b(?:es|en)\s*:/, 'labels.ts declares its own translations');
});

test('owner is known, translated and not offered as an editable role', () => {
  assert.equal(ROLE_DEFINITIONS.owner.assignable, false);
  assert.equal(roleKey('owner'), 'roles.owner');
  assert.deepEqual([...ASSIGNABLE_ROLE_CODES], ['administrator', 'operator', 'referee', 'viewer']);
  assert.ok(!ASSIGNABLE_ROLE_CODES.includes('owner' as never), 'owner must not be assignable');
  for (const code of ROLE_CODES) {
    const expected = EXPECTED_ROLES[code]!.assignable;
    assert.equal(ROLE_DEFINITIONS[code].assignable, expected, `${code} has the wrong assignable flag`);
    assert.equal(ASSIGNABLE_ROLE_CODES.includes(code as never), expected, `${code} assignable mismatch`);
    assert.equal(isAssignableRole(code), expected, `isAssignableRole(${code}) is wrong`);
  }
  assert.equal(isAssignableRole('steward'), false);
  assert.equal(isAssignableRole(null), false);
  assert.equal(roleKey('  owner  '), 'roles.owner', 'known codes are recognized around blanks');
});

test('maps an unknown role to itself so it is shown as received', () => {
  assert.equal(roleKey('steward'), 'steward');
  assert.equal(roleKey('admin'), 'admin', 'an unofficial code is not translated (RF-026)');
  assert.equal(roleKey(''), '');
  assert.equal(roleKey(null), '');
  assert.equal(roleKey(undefined), '');
});

test('maps the four invitation statuses to translation keys', () => {
  assert.deepEqual(INVITATION_STATUS_LABEL_KEYS, {
    pending: 'invitationStatus.pending',
    accepted: 'invitationStatus.accepted',
    expired: 'invitationStatus.expired',
    revoked: 'invitationStatus.revoked',
  });
  assert.equal(invitationStatusLabelKey('pending'), 'invitationStatus.pending');
  assert.equal(invitationStatusLabelKey('accepted'), 'invitationStatus.accepted');
  assert.equal(invitationStatusLabelKey('expired'), 'invitationStatus.expired');
  assert.equal(invitationStatusLabelKey('revoked'), 'invitationStatus.revoked');
});

test('maps the two member statuses to translation keys', () => {
  assert.deepEqual(MEMBER_STATUS_LABEL_KEYS, {
    active: 'memberStatus.active',
    inactive: 'memberStatus.inactive',
  });
  assert.equal(memberStatusLabelKey('active'), 'memberStatus.active');
  assert.equal(memberStatusLabelKey('inactive'), 'memberStatus.inactive');
});

test('an unknown or missing status is returned verbatim so it is shown as received', () => {
  // La función devuelve el valor crudo y `t()` lo devuelve tal cual cuando no
  // existe como clave: nunca se inventa una traducción (RF-026).
  assert.equal(invitationStatusLabelKey('consumed'), 'consumed');
  assert.equal(invitationStatusLabelKey(''), '');
  assert.equal(invitationStatusLabelKey(null), '');
  assert.equal(memberStatusLabelKey('suspended'), 'suspended');
  assert.equal(memberStatusLabelKey(null), '');
});

test('the five roles have their exact Spanish and English labels', () => {
  const { spanish, english } = catalogSlices();
  const spanishCatalog = catalogMap(spanish);
  const englishCatalog = catalogMap(english);

  for (const code of ROLE_CODES) {
    const key = `roles.${code}`;
    assert.equal(spanish.split(`'${key}':`).length - 1, 1, `${key} is not declared exactly once in Spanish`);
    assert.equal(english.split(`'${key}':`).length - 1, 1, `${key} is not declared exactly once in English`);
    assert.equal(spanishCatalog.get(key), EXPECTED_ROLES[code]!.es, `wrong Spanish label for ${key}`);
    assert.equal(englishCatalog.get(key), EXPECTED_ROLES[code]!.en, `wrong English label for ${key}`);
  }
});

test('the roles are localized through the existing translator and fall back to the code', () => {
  const { spanish, english } = catalogSlices();
  const spanishCatalog = catalogMap(spanish);
  const englishCatalog = catalogMap(english);
  const tEs = (key: string): string => spanishCatalog.get(key) ?? key;
  const tEn = (key: string): string => englishCatalog.get(key) ?? key;

  for (const code of ROLE_CODES) {
    assert.equal(tEs(roleKey(code)), EXPECTED_ROLES[code]!.es, `wrong Spanish label for ${code}`);
    assert.equal(tEn(roleKey(code)), EXPECTED_ROLES[code]!.en, `wrong English label for ${code}`);
  }

  // `t()` devuelve la clave recibida cuando no existe: la etiqueta es el código.
  assert.equal(tEs(roleKey('steward')), 'steward');
  assert.equal(tEn(roleKey('steward')), 'steward');
  assert.equal(roleKey('owner') && tEs(roleKey('owner')), 'Dueño');
});

test('the role keys keep exact Spanish and English parity', () => {
  const { spanish, english } = catalogSlices();
  const expected = ROLE_CODES.map((code) => `roles.${code}`);
  const roleKeysOf = (slice: string): string[] =>
    [...catalogMap(slice).keys()].filter((key) => key.startsWith('roles.'));

  assert.deepEqual([...roleKeysOf(spanish)].sort(), [...expected].sort());
  assert.deepEqual([...roleKeysOf(english)].sort(), [...expected].sort());
});

test('keeps the Spanish and English catalogs in parity for the new keys', () => {
  const { spanish, english } = catalogSlices();
  const keyPattern = /^\s*'([^']+)':/gm;
  const keysOf = (source: string): Set<string> =>
    new Set(Array.from(source.matchAll(keyPattern), (match) => match[1] ?? ''));

  const spanishKeys = keysOf(spanish);
  const englishKeys = keysOf(english);
  assert.ok(spanishKeys.size > 0, 'the Spanish catalog has no keys');
  assert.ok(englishKeys.size > 0, 'the English catalog has no keys');
  assert.deepEqual([...spanishKeys].sort(), [...englishKeys].sort());
});

test('the 23 position keys exist in both catalogs with exact es/en parity', () => {
  const { spanish, english } = catalogSlices();
  const keyPattern = /^\s*'(positions\.[^']+)':/gm;
  const positionKeysOf = (source: string): string[] =>
    Array.from(source.matchAll(keyPattern), (match) => match[1] ?? '');

  const expected = POSITION_CODES.map((code) => positionKey(code));
  assert.equal(expected.length, 23, 'the position catalog must cover 23 codes');
  assert.deepEqual([...positionKeysOf(spanish)].sort(), [...expected].sort());
  assert.deepEqual([...positionKeysOf(english)].sort(), [...expected].sort());
});

test('the role select and the member directory use the single role source', () => {
  assert.match(MEMBERS_PAGE, /from '~\/utils\/labels'/, 'the members page does not use the single source');
  assert.match(MEMBERS_PAGE, /ASSIGNABLE_ROLE_CODES/, 'the members page hardcodes the assignable roles');
  assert.match(MEMBERS_PAGE, /t\(roleKey\(role\)\)/, 'the role select does not translate through t()');
  assert.match(
    MEMBERS_PAGE,
    /:aria-label="invitationAria\(action, invitation\)"/,
    'the invitation control keeps its accessible name',
  );
  assert.match(
    MEMBERS_PAGE,
    /t\(memberStatusLabelKey\(member\.is_active \? 'active' : 'inactive'\)\)/,
    'the member status is not translated',
  );
  assert.doesNotMatch(
    MEMBERS_PAGE,
    /const roles\s*:\s*MemberRole\[\]\s*=\s*\[/,
    'the members page declares a second role table',
  );
});

test('owner is shown translated and disabled in the member directory', () => {
  assert.match(
    MEMBERS_PAGE,
    /<option v-if="!isAssignableRole\(member\.role_code\)"[^>]*>\{\{ t\(roleKey\(member\.role_code\)\) \}\}<\/option>/,
    'the owner (and any non-editable role) is not rendered through the role source',
  );
  assert.match(
    MEMBERS_PAGE,
    /:disabled="member\.role_code === 'owner' \|\| saving"/,
    'the owner role must stay non-editable and the comparison must use the code',
  );
  assert.match(
    MEMBERS_PAGE,
    /if \(member\.role_code === 'owner' \|\| member\.role_code === role_code\) return;/,
    'the role guard must compare codes, never labels',
  );
});

test('the members and invitation screens render labels instead of raw role codes', () => {
  assert.match(MEMBERS_PAGE, /t\(roleKey\(invitation\.role_code\)\)/);
  assert.match(MEMBERS_PAGE, /t\(invitationStatusLabelKey\(/);
  assert.match(MEMBERS_PAGE, /t\(memberStatusLabelKey\(/);
  assert.match(MEMBERS_PAGE, /:aria-label="t\('members\.generatedLinkAria'\)"/);

  assert.match(INVITATION_PAGE, /from '~\/utils\/labels'/, 'the invitation page does not use the single source');
  assert.match(INVITATION_PAGE, /t\(roleKey\(preview\.role_code\)\)/);

  // Sin falsos positivos: los atributos (`:value="member.role_code"`) y las
  // comparaciones (`role_code === 'owner'`) usan el código y son legítimos.
  const rawRoleMustache = /\{\{\s*(?:[A-Za-z_$][\w$]*\s*\.\s*)*role(?:_code)?\s*\}\}/;
  for (const { name, source } of VIEW_FILES) {
    assert.doesNotMatch(
      source,
      rawRoleMustache,
      `${name} paints a raw role code instead of its label`,
    );
  }
});

test('no view duplicates role labels: they only live in the language catalog', () => {
  const labels = Object.values(EXPECTED_ROLES).flatMap((role) => [role.es, role.en]);
  for (const { name, source } of APP_FILES) {
    if (name === 'composables/useI18n.ts') continue;
    for (const label of labels) {
      assert.ok(
        !source.includes(`'${label}'`) && !source.includes(`"${label}"`) && !source.includes(`\`${label}\``),
        `${name} duplicates the role label "${label}"`,
      );
    }
  }
});

test('the read-only configuration notices exist in both catalogs', () => {
  const { spanish, english } = catalogSlices();
  const keys = ['setup.readOnlyMode', 'wizard.readOnly'];

  for (const key of keys) {
    const pattern = new RegExp(`'${key.replace(/\./g, '\\.')}':`);
    assert.match(spanish, pattern, `missing Spanish key ${key}`);
    assert.match(english, pattern, `missing English key ${key}`);
  }
});

// RF-029: ninguna vista puede pintar el identificador de una clave. El barrido
// deriva las claves del **propio código** (`t('…')`, `t("…")`, `t(`…`)`
// estáticas y las tablas declarativas: `…Key: '…'`, `key: '…'` de las fuentes
// únicas de roles/posiciones y los mapas `*_LABEL_KEYS`), y las compara con los
// catálogos es/en. No hay lista escrita a mano que pueda desactualizarse: si
// aparece una clave nueva en una vista, entra sola en el barrido.
test('every translation key used by the app exists in both catalogs', () => {
  const used = extractUsedKeys(APP_FILES);
  const { spanish, english } = catalogSlices();
  const spanishKeys = catalogKeys(spanish);
  const englishKeys = catalogKeys(english);

  assert.ok(used.size > 0, 'the sweep found no translation keys');
  assert.ok(spanishKeys.length > 0, 'the Spanish catalog has no keys');
  assert.ok(englishKeys.length > 0, 'the English catalog has no keys');

  const missingSpanish = findMissingKeys(used.keys(), spanishKeys);
  const missingEnglish = findMissingKeys(used.keys(), englishKeys);
  assert.deepEqual(
    missingSpanish,
    [],
    `keys used by the app but missing from the Spanish catalog: ${missingSpanish.join(', ')}`,
  );
  assert.deepEqual(
    missingEnglish,
    [],
    `keys used by the app but missing from the English catalog: ${missingEnglish.join(', ')}`,
  );

  // La clave del aviso de fallo del sorteo forma parte del barrido: se usa en
  // la ruta del calendario y debe existir en los dos idiomas.
  assert.ok(used.has('setup.noScheduleGeneration'), 'the schedule failure notice is not used');
});

test('the sweep detects a key that is absent from the catalog', () => {
  const used = extractUsedKeys([
    {
      name: 'fixture.vue',
      source: [
        "{{ t('common.login') }}",
        '{{ t("common.logout") }}',
        "{{ t(`wizard.next`) }}",
        "{{ t('missing.fromTheSweep') }}",
      ].join('\n'),
    },
    {
      name: 'fixture.ts',
      source: [
        "const step = { labelKey: 'wizard.rules.scoring' };",
        "const issue = { messageKey: 'stage.wizard.partial' };",
        "const position = { key: 'positions.GK' };",
        'const INVITATION_STATUS_LABEL_KEYS = { pending: \'invitationStatus.pending\' } as const;',
      ].join('\n'),
    },
  ]);

  assert.deepEqual([...used.keys()].sort(), [
    'common.login',
    'common.logout',
    'invitationStatus.pending',
    'missing.fromTheSweep',
    'positions.GK',
    'stage.wizard.partial',
    'wizard.next',
    'wizard.rules.scoring',
  ]);
  assert.deepEqual(
    findMissingKeys(used.keys(), [
      'common.login',
      'common.logout',
      'invitationStatus.pending',
      'positions.GK',
      'stage.wizard.partial',
      'wizard.next',
      'wizard.rules.scoring',
    ]),
    ['missing.fromTheSweep'],
  );
});

// RF-029 / RNF-004: toda copia visible sale del catálogo, para que siga al
// idioma activo. El barrido lee los nodos de texto y los atributos visibles
// estáticos de cada plantilla; la lista blanca solo admite lo que no se traduce
// (RF-030): la marca «BRACKET CRAFT», la notación del enfrentamiento «vs» y los
// códigos de equipo de la vista previa de la portada («RIV», «ATL»). Cualquier
// texto nuevo escrito a mano cae solo, sin actualizar ninguna lista de claves.
const ALLOWED_VISIBLE_LITERALS = new Set(['BRACKET CRAFT', 'VS', 'RIV', 'ATL']);

test('no view shows fixed text outside the language catalog', () => {
  const literals = extractVisibleLiterals(APP_FILES)
    .filter((entry) => !ALLOWED_VISIBLE_LITERALS.has(entry.text.toUpperCase()));

  assert.deepEqual(
    literals.map((entry) => `${entry.file}: ${entry.text}`),
    [],
    'visible text must come from t() so it follows the active language',
  );
});

test('the literal sweep ignores interpolations, comments and bound attributes', () => {
  const literals = extractVisibleLiterals([
    {
      name: 'fixture.vue',
      source: [
        '<template>',
        "  <p>{{ t('home.title') }} · inicia {{ tournament.start_date }}</p>",
        '  <p>Season starts</p>',
        '  <input :placeholder="t(\'home.title\')" placeholder="Escribe aquí" />',
        '  <a :title="t(\'home.title\')"><!-- <span>Comentario</span> --></a>',
        '</template>',
      ].join('\n'),
    },
  ]);

  assert.deepEqual(
    literals.map((entry) => entry.text),
    ['· inicia', 'Season starts', 'Escribe aquí'],
  );
});

// RF-029 / RNF-004: las superficies del alcance tienen sus textos en los dos
// idiomas. Las claves salen de las pantallas reales (ninguna clave muerta). El
// aviso de formato distinto de 11v11 y la ayuda de los límites de plantilla se
// verifican aquí (RF-043, RF-044).
const SCREEN_KEYS: Readonly<Record<string, readonly string[]>> = {
  asistentes: ['wizard.stepCount', 'wizard.announce', 'wizard.blocked', 'wizard.readOnly'],
  reglas: ['wizard.rules.scoring', 'rules.gameFormatHint', 'rules.limitsHelp', 'format.notice.rules'],
  fases: ['stage.wizard.partial', 'stage.wizard.createAmbiguous'],
  equipos: ['teams.wizard.rowError', 'teams.wizard.pathBulk'],
  plantillas: [
    'tournament.rosters.lockNotice',
    'tournament.rosters.addTitle',
    'tournament.rosters.backToOperation',
  ],
  calendario: ['tournament.calendar.title', 'setup.noScheduleGeneration'],
};

test('the screens of the scope have their texts in both languages', () => {
  const { spanish, english } = catalogSlices();
  const spanishCatalog = catalogMap(spanish);
  const englishCatalog = catalogMap(english);

  for (const [screen, keys] of Object.entries(SCREEN_KEYS)) {
    for (const key of keys) {
      assert.ok(spanishCatalog.get(key), `${screen}: missing Spanish text for ${key}`);
      assert.ok(englishCatalog.get(key), `${screen}: missing English text for ${key}`);
    }
  }
});

test('the parity check fails when one catalog has an extra key', () => {
  assert.deepEqual(catalogParity(['a.one', 'a.two'], ['a.one', 'a.two']), {
    onlySpanish: [],
    onlyEnglish: [],
  });
  assert.deepEqual(catalogParity(['a.one', 'a.two'], ['a.one', 'a.three']), {
    onlySpanish: ['a.two'],
    onlyEnglish: ['a.three'],
  });
});

test('the catalogs have the same keys, each declared once and never empty', () => {
  const { spanish, english } = catalogSlices();
  const spanishKeys = catalogKeys(spanish);
  const englishKeys = catalogKeys(english);

  assert.deepEqual(catalogParity(spanishKeys, englishKeys), {
    onlySpanish: [],
    onlyEnglish: [],
  });

  for (const [locale, keys] of [['Spanish', spanishKeys], ['English', englishKeys]] as const) {
    const duplicates = keys.filter((key, index) => keys.indexOf(key) !== index);
    assert.deepEqual(duplicates, [], `${locale} catalog declares duplicated keys`);
  }

  for (const [locale, map] of [
    ['Spanish', catalogMap(spanish)],
    ['English', catalogMap(english)],
  ] as const) {
    for (const [key, value] of map) {
      assert.ok(value.trim().length > 0, `${locale} catalog has an empty value for ${key}`);
    }
  }
});
