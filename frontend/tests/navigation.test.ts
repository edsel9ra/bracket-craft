import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { getApiStatus, isForbidden, isUnauthorized } from '../app/utils/api.ts';
import {
  matchOperationPath,
  matchSelectionKey,
  readMatchSelection,
  rosterReturnHref,
  teamRosterHref,
  writeMatchSelection,
} from '../app/utils/matchNavigation.ts';
import { safeInternalRedirect } from '../app/utils/navigation.ts';
import {
  legacySectionRedirect,
  matchIdFromPath,
  tournamentSectionForPath,
  tournamentSectionHref,
  type TournamentSection,
} from '../app/utils/tournamentNavigation.ts';
import { isSafeCsrfToken, normalizeOrganizationId, normalizeUuid } from '../app/utils/validation.ts';
import { entryStepWrite, stepFromAddress, stepFromLocation } from '../app/utils/wizardStep.ts';

test('accepts a same-origin internal path', () => {
  assert.equal(safeInternalRedirect('/workspace?tab=matches'), '/workspace?tab=matches');
});

test('rejects external and protocol-relative redirects', () => {
  assert.equal(safeInternalRedirect('https://evil.example', '/workspace'), '/workspace');
  assert.equal(safeInternalRedirect('//evil.example/path', '/workspace'), '/workspace');
  assert.equal(safeInternalRedirect('/\\\\evil.example', '/workspace'), '/workspace');
});

test('accepts only valid organization UUIDs', () => {
  const organizationId = '123e4567-e89b-12d3-a456-426614174000';
  assert.equal(normalizeOrganizationId(` ${organizationId} `), organizationId);
  assert.equal(normalizeOrganizationId('not-an-organization'), null);
});

test('normalizes public tournament UUIDs', () => {
  const tournamentId = '123e4567-e89b-12d3-a456-426614174000';
  assert.equal(normalizeUuid(` ${tournamentId} `), tournamentId);
  assert.equal(normalizeUuid('not-a-uuid'), null);
});

test('classifies API failures and rejects unsafe CSRF values', () => {
  assert.equal(getApiStatus({ statusCode: 401 }), 401);
  assert.equal(isUnauthorized({ status: 401 }), true);
  assert.equal(isForbidden({ statusCode: 403 }), true);
  assert.equal(isSafeCsrfToken('token-value'), true);
  assert.equal(isSafeCsrfToken('token\nvalue'), false);
});

// RF-018: la sección activa sale de la ruta y nunca de un valor fijo de la pantalla.
test('derives the active tournament section from the route', () => {
  const tournamentPath = '/workspace/tournaments/t1';

  assert.equal(tournamentSectionForPath(tournamentPath), 'configuration');
  assert.equal(tournamentSectionForPath(`${tournamentPath}#resumen`), 'summary');
  assert.equal(tournamentSectionForPath(tournamentPath, '#configuracion'), 'configuration');
  assert.equal(tournamentSectionForPath(tournamentPath, '#equipos'), 'configuration');
  assert.equal(tournamentSectionForPath(`${tournamentPath}/calendar`), 'calendar');
  assert.equal(tournamentSectionForPath(`${tournamentPath}/rosters/`), 'rosters');
  assert.equal(tournamentSectionForPath('/workspace/matches/m1'), 'operation');
  assert.equal(tournamentSectionForPath('/workspace/matches/m1#operacion'), 'operation');
});

// RF-018: el índice enlaza con direcciones propias, no con anclas para las secciones que las tienen.
test('builds real tournament section links', () => {
  const tournamentId = 't1';

  assert.equal(tournamentSectionHref('summary', { tournamentId }), '/workspace/tournaments/t1#resumen');
  assert.equal(tournamentSectionHref('configuration', { tournamentId }), '/workspace/tournaments/t1#configuracion');
  assert.equal(tournamentSectionHref('calendar', { tournamentId }), '/workspace/tournaments/t1/calendar');
  assert.equal(tournamentSectionHref('rosters', { tournamentId }), '/workspace/tournaments/t1/rosters');
  assert.equal(tournamentSectionHref('operation', { tournamentId }), null);
  assert.equal(
    tournamentSectionHref('operation', { tournamentId, matchId: 'm1' }),
    '/workspace/matches/m1#operacion',
  );
  assert.equal(matchIdFromPath('/workspace/matches/m1#operacion'), 'm1');
  assert.equal(matchIdFromPath('/workspace/tournaments/t1/calendar'), null);
});

// RF-020: los fragmentos con dirección propia redirigen reemplazando la entrada de historial.
test('redirects legacy section fragments with history replacement', () => {
  assert.deepEqual(legacySectionRedirect('t1', '#calendario', '?stage=s1'), {
    path: '/workspace/tournaments/t1/calendar',
    query: { stage: 's1' },
    replace: true,
  });
  assert.deepEqual(legacySectionRedirect('t1', '#calendario'), {
    path: '/workspace/tournaments/t1/calendar',
    query: {},
    replace: true,
  });
  assert.deepEqual(legacySectionRedirect('t1', '#plantillas'), {
    path: '/workspace/tournaments/t1/rosters',
    query: {},
    replace: true,
  });
});

// RF-020: #resumen, #configuracion y #equipos siguen resolviendo a su ancla.
test('keeps current tournament anchors and ignores unknown fragments', () => {
  for (const hash of ['#resumen', '#configuracion', '#equipos', '#desconocido']) {
    assert.equal(legacySectionRedirect('t1', hash), null, hash);
  }
  assert.equal(legacySectionRedirect('t1', ''), null);
});

// RF-020: un fragmento de operación sin partido lleva al listado de partidos
// del calendario, que es donde vive ahora, sin inventar un partido.
test('sends a matchless operation fragment to the calendar match list', () => {
  assert.deepEqual(legacySectionRedirect('t1', '#operacion'), {
    path: '/workspace/tournaments/t1/calendar',
    query: {},
    hash: '#operacion',
    replace: true,
  });
  assert.deepEqual(legacySectionRedirect('t1', '#operacion', '?stage=s1'), {
    path: '/workspace/tournaments/t1/calendar',
    query: { stage: 's1' },
    hash: '#operacion',
    replace: true,
  });
});

const configurationPage = readFileSync(
  new URL('../app/pages/workspace/tournaments/[id]/index.vue', import.meta.url),
  'utf8',
);
const calendarPage = readFileSync(
  new URL('../app/pages/workspace/tournaments/[id]/calendar.vue', import.meta.url),
  'utf8',
);

// RF-018/RF-021: la configuración queda con resumen, reglas, fases y equipos;
// el calendario y las plantillas dejan de replicarse en ella.
test('configuration keeps only summary, rules, stages and teams', () => {
  for (const anchor of ['id="resumen"', 'id="configuracion"', 'id="equipos"']) {
    assert.ok(configurationPage.includes(anchor), `missing anchor ${anchor}`);
  }
  for (const removed of ['id="plantillas"', 'id="calendario"', 'id="operacion"']) {
    assert.ok(!configurationPage.includes(removed), `configuration still renders ${removed}`);
  }
  assert.doesNotMatch(configurationPage, /matches\/draw/);
  assert.doesNotMatch(configurationPage, /rosters\/bulk/);
});

// RF-023/RF-024: el calendario reutiliza el contrato existente de creación y
// sorteo, conserva la confirmación de reemplazo y no descarga las plantillas.
test('calendar owns match creation and the single schedule generator', () => {
  assert.ok(calendarPage.includes('id="operacion"'), 'the match list is not on the calendar');
  assert.equal(calendarPage.match(/matches\/draw/g)?.length, 1, 'there must be exactly one generator call');
  assert.match(calendarPage, /confirmRegenerateSchedule/);
  assert.match(calendarPage, /replace_existing/);
  assert.match(calendarPage, /legs: scheduleForm\.legs/);
  assert.match(calendarPage, /seed,/);
  assert.match(calendarPage, /`\/tournaments\/\$\{tournamentId\}\/matches`, \{/);
  assert.doesNotMatch(calendarPage, /\/rosters/);
});

const matchPage = readFileSync(
  new URL('../app/pages/workspace/matches/[id].vue', import.meta.url),
  'utf8',
);
const rostersPage = readFileSync(
  new URL('../app/pages/workspace/tournaments/[id]/rosters.vue', import.meta.url),
  'utf8',
);
const workspaceShell = readFileSync(
  new URL('../app/components/WorkspaceShell.vue', import.meta.url),
  'utf8',
);
const wizardShell = readFileSync(
  new URL('../app/components/wizard/WizardShell.vue', import.meta.url),
  'utf8',
);
const rulesWizard = readFileSync(
  new URL('../app/components/rules/RulesWizard.vue', import.meta.url),
  'utf8',
);
const stageTeamsWizard = readFileSync(
  new URL('../app/components/StageTeamsWizard.vue', import.meta.url),
  'utf8',
);
const teamsWizard = readFileSync(
  new URL('../app/components/TeamsWizard.vue', import.meta.url),
  'utf8',
);

/** Etiqueta de apertura de un componente o botón, para no cruzar de un bloque a otro. */
function openingTag(source: string, marker: string): string {
  const start = source.indexOf(marker);
  assert.ok(start >= 0, `missing ${marker}`);
  const end = source.indexOf('>', start);
  return source.slice(start, end + 1);
}

// RF-038: la entrada «Configuración» del índice no depende de un permiso; el
// único cambio es de visibilidad y ninguna capacidad se habilita por ello.
test('the tournament index offers configuration without a permission condition', () => {
  const tournamentLinks = workspaceShell.slice(
    workspaceShell.indexOf('const tournamentLinks'),
    workspaceShell.indexOf('async function resolvePlatformAccess'),
  );
  assert.match(tournamentLinks, /\{ key: 'configuration', label: t\('shell\.configuration'\) \}/);
  assert.doesNotMatch(tournamentLinks, /canManage|hasPermission/);
});

// RF-038/RF-018: sin permiso de gestión la configuración se muestra en solo
// lectura, anuncia el modo y no ofrece ninguna acción de escritura; las tres
// superficies de escritura heredan el modo del permiso existente.
test('an observer reads the configuration without any write action', () => {
  assert.match(
    configurationPage,
    /const configurationReadOnly = computed\(\(\) => !canManageTournaments\.value\)/,
    'the read-only mode must come from the existing organization permission',
  );
  assert.match(
    configurationPage,
    /v-if="configurationReadOnly"[\s\S]{0,200}?t\('setup\.readOnlyMode'\)/,
    'the observer has no read-only notice',
  );

  for (const action of ['publishVersion', 'createDraftVersion', 'useDefaultRules']) {
    const button = configurationPage.slice(
      configurationPage.lastIndexOf('<button', configurationPage.indexOf(`@click="${action}"`)),
      configurationPage.indexOf('>', configurationPage.indexOf(`@click="${action}"`)) + 1,
    );
    assert.match(button, /v-(?:else-)?if="canManageTournaments/, `${action} is offered without permission`);
  }

  const rulesTag = openingTag(configurationPage, '<RulesWizard');
  const stagesTag = openingTag(configurationPage, '<StageTeamsWizard');
  const teamsTag = openingTag(configurationPage, '<TeamsWizard');
  assert.match(rulesTag, /:disabled="!canManageTournaments \|\| !rulesEditable"/);
  assert.match(stagesTag, /:disabled="!canManageTournaments \|\| activeVersion\?\.status !== 'draft'"/);
  assert.match(teamsTag, /:disabled="!canManageTournaments \|\| activeVersion\?\.status !== 'draft'"/);
});

// RF-038: el asistente conserva sus valores y pasos en solo lectura, anuncia el
// modo y oculta confirmar; con permiso, la misma condición lo mantiene visible.
test('the wizards switch to a read-only mode without a confirm action', () => {
  assert.match(wizardShell, /v-if="!readOnly"[\s\S]{0,240}?t\('wizard\.confirm'\)/);
  assert.match(wizardShell, /v-if="readOnly"[\s\S]{0,200}?t\('wizard\.readOnly'\)/);

  const wizards = { rules: rulesWizard, phases: stageTeamsWizard, teams: teamsWizard };
  for (const [name, source] of Object.entries(wizards)) {
    assert.match(source, /:read-only="disabled"/, `${name} does not apply the read-only mode to the shell`);
  }

  assert.match(rulesWizard, /v-if="!disabled"[\s\S]{0,260}?@click="confirmSave"/);
  assert.match(stageTeamsWizard, /v-else-if="!disabled"[\s\S]{0,260}?@click="confirm"/);
  assert.match(teamsWizard, /v-if="!disabled"[\s\S]{0,260}?@click="confirm"/);
});

// RF-021: el alta individual de jugadores tiene una sola pantalla responsable,
// la administración de plantillas; la operación ya no la replica ni la envía.
test('operation no longer registers players', () => {
  assert.doesNotMatch(matchPage, /rosterForm/);
  assert.doesNotMatch(matchPage, /addRosterPlayer/);
  // Ni una sola escritura a la ruta de plantillas desde la operación; el único
  // camino a esa ruta es el enlace a la pantalla que sí da de alta.
  const rosterPathLines = matchPage.split('\n').filter((line) => line.includes('/rosters'));
  assert.ok(rosterPathLines.length > 0, 'the roster link is missing');
  assert.ok(
    rosterPathLines.every((line) => !line.includes('request')),
    `operation still calls the roster endpoint: ${rosterPathLines.join(' | ')}`,
  );
  for (const field of ['national_id', 'birth_date', 'photo_consent']) {
    assert.ok(!matchPage.includes(field), `operation still handles the roster field ${field}`);
  }
  // La única pantalla que da de alta jugadores sigue enviando la escritura.
  assert.match(rostersPage, /`\/tournaments\/\$\{tournamentId\}\/rosters`/);
  assert.match(rostersPage, /method: 'POST'/);
});

// RF-022: la operación enlaza a la plantilla del equipo —torneo y equipo
// identificados— y conserva el contexto de retorno a esa misma operación.
// No hay redirección abierta: el retorno solo puede ser una ruta interna del
// partido, construida aquí y no recibida de la dirección.
test('operation links to the team roster keeping the return context', () => {
  const href = teamRosterHref({ tournamentId: 't1', teamId: 'team 1', matchId: 'm1' });
  assert.equal(
    href,
    '/workspace/tournaments/t1/rosters?team=team%201&returnTo=%2Fworkspace%2Fmatches%2Fm1%23operacion',
  );

  const url = new URL(href, 'https://app.test');
  assert.equal(url.pathname, '/workspace/tournaments/t1/rosters');
  assert.equal(url.searchParams.get('team'), 'team 1');
  assert.equal(url.searchParams.get('returnTo'), matchOperationPath('m1'));
  assert.equal(matchOperationPath('m1'), '/workspace/matches/m1#operacion');
  assert.ok(url.searchParams.get('returnTo')?.startsWith('/workspace/matches/'));

  assert.match(matchPage, /teamRosterHref\(/);
  assert.match(matchPage, /t\('match\.openTeamRoster'/);
});

// RF-022: al volver desde plantillas se conserva el partido (dirección), el
// segmento seleccionado (guardado por usuario, organización y partido en la
// sesión de la pestaña) y el borrador local de eventos y marcador, que se
// restaura al montar.
test('restores the selected segment and the local draft when returning from the roster', () => {
  const key = matchSelectionKey({ userId: 'u1', organizationId: 'o1', matchId: 'm1' });
  assert.equal(key, 'bc_match_selection:u1:o1:m1');

  const stored = writeMatchSelection('s2');
  assert.equal(readMatchSelection(stored, ['s1', 's2']), 's2');
  assert.equal(readMatchSelection(stored, ['s1']), null);
  assert.equal(readMatchSelection(stored, []), null);
  assert.equal(readMatchSelection(null, ['s2']), null);
  assert.equal(readMatchSelection('not-json', ['s2']), null);
  assert.equal(readMatchSelection(JSON.stringify({ segment_id: 2 }), ['s2']), null);

  assert.match(matchPage, /restoreSelectedSegment\(\)/);
  assert.match(matchPage, /persistSelectedSegment\(/);
  // Spec 012, H3-T06: el borrador local se lee y se escribe por el módulo
  // saneado, que nunca persiste la resolución prevista.
  assert.match(matchPage, /createMatchDraftStore\(/);
  assert.match(matchPage, /draftStore\.value\.read\(\)/);
  assert.match(matchPage, /draftStore\.value\.save\(/);
  // El enlace a la plantilla no descarta el borrador: no pide confirmación de
  // salida porque el borrador y el segmento se restauran al volver.
  assert.match(matchPage, /onBeforeRouteLeave\(\(to\)/);
});

const i18nCatalog = readFileSync(
  new URL('../app/composables/useI18n.ts', import.meta.url),
  'utf8',
);

// RF-022: la vuelta desde plantillas solo se ofrece si el destino es la
// operación de un partido **de este torneo**. El contexto de retorno no abre
// ninguna redirección: se acepta únicamente una ruta interna de la operación y
// el partido debe estar entre los del torneo cargados con el contexto de la
// organización activa (el backend ya filtra por organización y torneo).
test('offers a return link only for an internal match of this tournament', () => {
  const context = { tournamentId: 't1', matchIds: ['m1', 'm2'] };

  assert.equal(rosterReturnHref('/workspace/matches/m1#operacion', context), matchOperationPath('m1'));
  assert.equal(rosterReturnHref('/workspace/matches/m2', context), matchOperationPath('m2'));
  assert.equal(rosterReturnHref(encodeURIComponent(matchOperationPath('m1')), context), null);

  // Partido de otro torneo o de otra organización: no está entre los del torneo.
  assert.equal(rosterReturnHref('/workspace/matches/m9#operacion', context), null);
  assert.equal(rosterReturnHref('/workspace/matches/m1#operacion', { tournamentId: 't1', matchIds: [] }), null);

  // Destino externo o fuera de la aplicación.
  assert.equal(rosterReturnHref('https://evil.example/workspace/matches/m1', context), null);
  assert.equal(rosterReturnHref('//evil.example/workspace/matches/m1', context), null);
  assert.equal(rosterReturnHref('/\\evil.example/workspace/matches/m1', context), null);
  assert.equal(rosterReturnHref('javascript:alert(1)', context), null);

  // Otra ruta interna, con parámetros o vacía.
  assert.equal(rosterReturnHref('/workspace/matches/m1?next=https://evil.example', context), null);
  assert.equal(rosterReturnHref('/workspace/tournaments/t1/rosters?team=t1', context), null);
  assert.equal(rosterReturnHref('/workspace/matches/', context), null);
  assert.equal(rosterReturnHref(undefined, context), null);
  assert.equal(rosterReturnHref('', context), null);
  assert.equal(rosterReturnHref(['/workspace/matches/m1#operacion'], context), null);
});

// RF-022: la pantalla de plantillas muestra el enlace de vuelta solo con un
// destino válido, con texto por i18n, y conserva el contexto de retorno al
// cambiar de equipo.
test('the roster page offers the return link only with a valid destination', () => {
  assert.match(rostersPage, /rosterReturnHref/);
  assert.match(
    rostersPage,
    /const returnToHref = computed\(\(\) => rosterReturnHref\(route\.query\.returnTo, \{/,
  );
  assert.match(
    rostersPage,
    /v-if="returnToHref"[\s\S]{0,240}?:href="returnToHref"[\s\S]{0,240}?t\('tournament\.rosters\.backToOperation'\)/,
    'el enlace de vuelta no es condicional o no está traducido',
  );
  // Al cambiar de equipo se conserva el resto de la dirección, incluido returnTo.
  assert.match(rostersPage, /\{ \.\.\.route\.query, team: next \}/);
  // Texto en los dos idiomas.
  assert.equal(
    i18nCatalog.match(/'tournament\.rosters\.backToOperation'/g)?.length,
    2,
    'la clave de vuelta debe existir en es y en',
  );
});

// RF-040: las pantallas del alcance solo usan el torneo de la ruta y validan
// los identificadores de la dirección contra los datos ya cargados de ese
// torneo; no aceptan torneo, organización, fase ni equipo de otra organización.
test('tournament screens accept no identifiers outside the active tournament', () => {
  for (const [name, source] of Object.entries({ rosters: rostersPage, calendar: calendarPage })) {
    assert.match(source, /const tournamentId = String\(route\.params\.id\)/, `${name} no toma el torneo de la ruta`);
    assert.doesNotMatch(
      source,
      /route\.query\.(organizationId|organization_id|tournamentId|tournament_id)/,
      `${name} acepta un identificador de organización o torneo por la dirección`,
    );
    assert.doesNotMatch(source, /\$fetch|useFetch\(/, `${name} no usa el cliente HTTP central`);
  }

  // La fase de la dirección solo vale si está entre las fases del torneo cargadas.
  assert.match(
    calendarPage,
    /versionStages\.some\(\(stage\) => stage\.id === requested\) \? requested : ''/,
    'el calendario acepta una fase ajena desde la dirección',
  );
  // El equipo de la dirección solo vale si está entre los equipos del torneo.
  assert.match(
    rostersPage,
    /teams\.value\.some\(\(team\) => team\.team_id === requested\)/,
    'las plantillas aceptan un equipo ajeno desde la dirección',
  );
  // La vuelta valida el partido contra los partidos del torneo.
  assert.match(rostersPage, /matchIds: tournamentMatchIds\.value/);
});

// ---------------------------------------------------------------------------
// Spec 025: orden, rótulos, ancla `#fases` y enlaces del recorrido
// ---------------------------------------------------------------------------

/** Rótulo de una clave en un idioma, leído del catálogo sin montar Vue. */
function messageLabel(locale: 'es' | 'en', key: string): string {
  const enStart = i18nCatalog.indexOf('\n  en: {');
  assert.ok(enStart > 0, 'el catálogo debe declarar los bloques es y en');
  const block = locale === 'es' ? i18nCatalog.slice(0, enStart) : i18nCatalog.slice(enStart);
  const label = block.match(new RegExp(`'${key}': '([^']*)'`))?.[1];
  assert.ok(label !== undefined, `falta ${key} en ${locale}`);
  return label;
}

// RF-001: el orden del documento es Reglas → Equipos → Fases, y se comprueba
// por la posición relativa de los tres asistentes, no solo por su presencia.
test('the configuration presents rules, then teams, then stages', () => {
  const positions = {
    rules: configurationPage.indexOf('<RulesWizard'),
    teams: configurationPage.indexOf('<TeamsWizard'),
    stages: configurationPage.indexOf('<StageTeamsWizard'),
  };
  for (const [name, position] of Object.entries(positions)) {
    assert.ok(position >= 0, `falta el asistente de ${name}`);
  }
  assert.ok(positions.rules < positions.teams, 'reglas debe preceder a equipos');
  assert.ok(positions.teams < positions.stages, 'equipos debe preceder a fases');
  // El orden de lectura sigue al del marcado: ningún tabindex positivo lo altera.
  assert.doesNotMatch(configurationPage, /tabindex="[1-9]/);
  // El bloque de equipos conserva su ancla y queda por delante del de fases.
  assert.ok(
    configurationPage.indexOf('id="equipos"') < positions.stages,
    'el bloque de equipos debe preceder al asistente de fases',
  );
});

// RF-003/RNF-004: la cadena exacta de los cuatro rótulos numerados en los dos
// idiomas, sin huecos ni repeticiones.
test('the four numbered section labels form one chain in both languages', () => {
  const keys = [
    'setup.rulesEyebrow',
    'setup.teamsEyebrow',
    'setup.stagesEyebrow',
    'setup.calendarEyebrow',
  ];
  assert.deepEqual(keys.map((key) => messageLabel('es', key)), [
    '01 · Reglas',
    '02 · Equipos',
    '03 · Fases',
    '04 · Calendario',
  ]);
  assert.deepEqual(keys.map((key) => messageLabel('en', key)), [
    '01 · Rules',
    '02 · Teams',
    '03 · Stages',
    '04 · Schedule',
  ]);

  // La numeración es consecutiva y cada rótulo lleva dos dígitos y `·`.
  for (const locale of ['es', 'en'] as const) {
    const numbers = keys.map((key) => messageLabel(locale, key).match(/^(\d{2}) · \S/)?.[1]);
    assert.deepEqual(numbers, ['01', '02', '03', '04'], locale);
  }
});

// RF-006: la lista de verificación conserva sus cinco ítems y su contenido, y
// solo cambia de orden: versión → equipos → fases → partidos → plantillas.
test('the pre-publish checklist keeps its five items in the new order', () => {
  const start = configurationPage.indexOf('const setupChecks = computed(() => [');
  const end = configurationPage.indexOf(']);', start);
  assert.ok(start >= 0 && end > start, 'no se encuentra setupChecks');
  const block = configurationPage.slice(start, end);

  const order = [
    'setup.versionDraft',
    'setup.teams',
    'setup.stages',
    'setup.matches',
    'setup.rosters',
  ].map((key) => [key, block.indexOf(`t('${key}')`)] as const);
  for (const [key, position] of order) {
    assert.ok(position >= 0, `el ítem ${key} falta en la checklist`);
  }
  for (let index = 1; index < order.length; index += 1) {
    assert.ok(
      order[index - 1]![1] < order[index]![1],
      `${order[index - 1]![0]} debe preceder a ${order[index]![0]}`,
    );
  }

  // Ni un ítem más ni uno menos: solo cambia su orden.
  assert.equal(block.match(/\{ label:/g)?.length, 5, 'la checklist debe tener cinco ítems');
  // El ítem «Equipos» sigue midiendo asignaciones de fase, no altas de equipo.
  assert.match(block, /label: t\('setup\.teams'\), detail: t\('setup\.assigned', \{ count: draftAssignedStageTeamCount\.value \}\)/);
});

// RF-004/RF-003/RNF-003: el panel del asistente de fases es el ancla `#fases`,
// pinta por primera vez su rótulo numerado y su título es enfocable.
test('the phases panel is the #fases anchor and shows its numbered title', () => {
  const panel = openingTag(stageTeamsWizard, '<section');
  assert.match(panel, /id="fases"/, 'el panel de fases no lleva id="fases"');

  const label = stageTeamsWizard.indexOf("t('setup.stagesEyebrow')");
  assert.ok(label >= 0, 'el rótulo «03 · Fases» no se pinta en el panel');
  assert.ok(
    label < stageTeamsWizard.indexOf('<WizardShell'),
    'el rótulo de la sección debe ir encima del asistente',
  );
  // El destino del ancla tiene título visible.
  assert.match(stageTeamsWizard, /title="t\('stage\.wizard\.title'\)"/);

  const heading = openingTag(wizardShell, '<h2');
  assert.match(heading, /:id="headingId"/, 'el título del asistente no es el que etiqueta el panel');
  assert.match(heading, /tabindex="-1"/, 'el título del bloque debe ser enfocable por teclado');
});

// RF-004/RF-005/RF-017: `#fases` resuelve sobre la configuración, no redirige,
// no cambia de sección y no añade ninguna ruta ni entrada de índice.
test('the #fases anchor resolves to the configuration section without a redirect', () => {
  assert.equal(tournamentSectionForPath('/workspace/tournaments/t1', '#fases'), 'configuration');
  assert.equal(tournamentSectionForPath('/workspace/tournaments/t1#fases'), 'configuration');
  assert.equal(legacySectionRedirect('t1', '#fases'), null);
  assert.equal(legacySectionRedirect('t1', '#fases', '?step=phases.identity'), null);
  // La entrada de configuración conserva su destino actual.
  assert.equal(
    tournamentSectionHref('configuration', { tournamentId: 't1' }),
    '/workspace/tournaments/t1#configuracion',
  );
});

// RF-005: el índice conserva sus cuatro entradas de configuración más la de
// operación condicionada, y no gana ninguna entrada «Fases».
test('the tournament index keeps four configuration entries and never offers phases', () => {
  const start = workspaceShell.indexOf('const tournamentLinks');
  const end = workspaceShell.indexOf('async function resolvePlatformAccess');
  assert.ok(start >= 0 && end > start, 'no se encuentra tournamentLinks');
  const block = workspaceShell.slice(start, end);

  const keys = [...block.matchAll(/\{ key: '([a-z]+)', label:/g)].map((match) => match[1] ?? '');
  assert.deepEqual(keys, ['summary', 'configuration', 'calendar', 'rosters', 'operation']);

  const context = { tournamentId: 't1' };
  assert.deepEqual(
    keys.filter((key) => tournamentSectionHref(key as TournamentSection, context) !== null),
    ['summary', 'configuration', 'calendar', 'rosters'],
  );
  assert.equal(
    tournamentSectionHref('operation', { ...context, matchId: 'm1' }),
    '/workspace/matches/m1#operacion',
  );
  // El ancla `#fases` no tiene entrada propia en el índice.
  assert.doesNotMatch(block, /fases/i, 'el índice del torneo no debe ofrecer una entrada de fases');
});

// RF-011/RF-012: abrir con `#fases` y sin paso normaliza la entrada una sola
// vez con `replace`, conserva el fragmento y no produce una segunda escritura.
test('normalizes the entry once, keeping the #fases fragment', () => {
  const location = '/workspace/tournaments/t1#fases';

  // El ancla no fija ni sustituye ningún paso: el asistente resuelve el suyo.
  assert.equal(stepFromLocation(location), null);
  assert.equal(stepFromAddress('phases', location), 'phases.identity');

  const firstWrite = entryStepWrite(location, stepFromAddress('phases', location));
  assert.ok(firstWrite, 'la entrada sin paso debe normalizarse una vez');
  assert.deepEqual(firstWrite, {
    mode: 'replace',
    url: '/workspace/tournaments/t1?step=phases.identity#fases',
  });

  // Aplicada la escritura, la dirección ya nombra el paso: no hay una segunda.
  const applied = firstWrite.url;
  assert.equal(entryStepWrite(applied, stepFromAddress('phases', applied)), null);
  assert.equal(stepFromAddress('phases', applied), 'phases.identity');

  // Con un paso ya presente no se reescribe nada, y el ancla no se pierde.
  const direct = '/workspace/tournaments/t1?step=teams.details#fases';
  assert.equal(entryStepWrite(direct, stepFromAddress('teams', direct)), null);
  assert.equal(stepFromAddress('teams', direct), 'teams.details');
});
