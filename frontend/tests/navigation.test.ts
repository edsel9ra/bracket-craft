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
} from '../app/utils/tournamentNavigation.ts';
import { isSafeCsrfToken, normalizeOrganizationId, normalizeUuid } from '../app/utils/validation.ts';

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
