import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import test from 'node:test';

import { extractUsedKeys } from '../app/utils/i18nCatalog.ts';
import {
  SEGMENT_PROPOSAL_HINT_LABEL_KEYS,
  applySegmentProposal,
  closeConflictMessageKey,
  segmentProposalHint,
} from '../app/utils/matchSegments.ts';
import { DOUBLE_YELLOW_INCONSISTENT_CODE } from '../app/utils/matchResolution.ts';
import {
  WALKOVER_REASONS,
  WALKOVER_REASON_LABEL_KEYS,
} from '../app/utils/matchClose.ts';

// Spec 017, T7 (RF-011, RF-015, RF-017, RNF-007). La pantalla de operación
// consume la propuesta del servidor y anuncia el acta cerrada. El proyecto no
// tiene arnés de componentes: aquí se comprueba lo que se puede probar con las
// utilidades puras (T6) y se barre la fuente para el cableado de la pantalla,
// que es el patrón que ya usa el repositorio (spec 015, T9).
//
// La prueba del botón de alta existe por una regresión real: en la 015 el botón
// «Añadir evento» desapareció de esta misma zona y solo lo detectó el E2E.

const PAGE = readFileSync(
  new URL('../app/pages/workspace/matches/[id].vue', import.meta.url),
  'utf8',
);
const TRANSLATIONS = readFileSync(
  new URL('../app/composables/useI18n.ts', import.meta.url),
  'utf8',
);

function catalogSlices(): { spanish: string; english: string } {
  const englishStart = TRANSLATIONS.indexOf('\n  en: {');
  assert.ok(englishStart > 0, 'the English catalog is missing');
  return {
    spanish: TRANSLATIONS.slice(0, englishStart),
    english: TRANSLATIONS.slice(englishStart),
  };
}

function catalogValues(slice: string): Map<string, string> {
  const values = new Map<string, string>();
  const pattern = /'((?:[^'\\]|\\.)*)':\s*'((?:[^'\\]|\\.)*)'/g;
  for (const match of slice.matchAll(pattern)) {
    values.set(match[1]!, match[2]!.replaceAll("\\'", "'"));
  }
  return values;
}

function appFiles(): { name: string; source: string }[] {
  const appDir = new URL('../app/', import.meta.url);
  return (readdirSync(appDir, { recursive: true }) as string[])
    .filter((file) => file.endsWith('.ts') || file.endsWith('.vue'))
    .map((file) => ({
      name: file.replaceAll('\\', '/'),
      source: readFileSync(new URL(file.replaceAll('\\', '/'), appDir), 'utf8'),
    }));
}

/** Línea de la plantilla que usa una clave, o `undefined` si no aparece. */
function pageLineWith(needle: string): string | undefined {
  return PAGE.split('\n').find((line) => line.includes(needle));
}

const NEW_TEXT_KEYS = [
  'match.doubleYellowInconsistent',
  'match.reportLocked',
  'match.segmentProposalDerived',
  'match.segmentProposalManual',
] as const;

// ---------------------------------------------------------------------------
// RF-015: el prerrelleno sale de la propuesta del servidor
// ---------------------------------------------------------------------------

test('the segment form is prefilled from the server proposal, not from a client sum', () => {
  // La operación trae `next_segment` y la pantalla lo aplica con las
  // utilidades puras; el número y el minuto no se calculan aquí.
  assert.match(PAGE, /next_segment/);
  assert.match(PAGE, /applySegmentProposal\(/);
  assert.match(PAGE, /forceMinuteOnRefresh\(/);
  assert.match(PAGE, /segment_number: segmentForm\.segment_number/);
  assert.match(PAGE, /minuteDirty: segmentForm\.minuteDirty/);

  // El cálculo local del número («último + 1») ya no existe…
  assert.doesNotMatch(
    PAGE,
    /segmentForm\.segment_number = Math\.max\(/,
    'the screen still computes the segment number on the client',
  );
  // …ni el minuto de la interrupción se copia al formulario a mano.
  assert.doesNotMatch(
    PAGE,
    /segmentForm\.minute_start = interruptionForm\.minute/,
    'the screen still copies the interruption minute by hand',
  );

  // Sin propuesta (partido terminal o versión no publicada) el formulario no
  // se bloquea: la utilidad devuelve el estado intacto.
  assert.deepEqual(
    applySegmentProposal({ segment_number: 4, minute_start: 12, minuteDirty: true }, null),
    { segment_number: 4, minute_start: 12, minuteDirty: true },
  );
});

test('a refresh never overwrites the minute the operator is writing', () => {
  // `refreshOperation` recibe el motivo: solo el montaje y crear o interrumpir
  // fuerzan el minuto; el refresco manual y el del socket no lo pisan.
  assert.match(PAGE, /refreshOperation\(cause: SegmentRefreshCause = 'refresh'\)/);
  assert.match(PAGE, /applyOperation\(value: MatchOperation, cause: SegmentRefreshCause = 'refresh'\)/);
  assert.match(PAGE, /applyOperation\(initialOperation\.value, 'mount'\)/);

  const forced = PAGE.split("refreshOperation('segment-changed')").length - 1;
  assert.equal(forced, 2, 'only creating and interrupting a segment force the minute');

  // El refresco que dispara el socket usa el motivo por defecto.
  const reload = PAGE.slice(PAGE.indexOf('const operationReload = createReloadCoordinator'));
  assert.match(
    reload.slice(0, 400),
    /await refreshOperation\(\);/,
    'the socket reload forces the minute',
  );

  // RF-015/D-5: con el minuto editado, la propuesta no lo pisa.
  assert.equal(
    segmentProposalHint({ segment_number: 3, minute_start: 30, derived: true }),
    'derived',
  );
});

test('the operator marks the minute as edited and the screen clears it after a segment change', () => {
  const minuteField = pageLineWith('v-model.number="segmentForm.minute_start"');
  assert.ok(minuteField, 'the starting minute field disappeared');
  assert.match(minuteField, /@input="markSegmentMinuteDirty"/);

  for (const action of ['function createSegment', 'async function interruptSegment']) {
    assert.ok(
      PAGE.slice(PAGE.indexOf(action), PAGE.indexOf(action) + 1400).includes(
        'segmentForm.minuteDirty = false',
      ),
      `${action} does not clear the edited minute`,
    );
  }
});

// ---------------------------------------------------------------------------
// Defectos registrados en MEMORY.md
// ---------------------------------------------------------------------------

test('the interruption minute goes through the guard and remembers the operator edit', () => {
  // El minuto del segmento activo no se copia a mano: pasa por la utilidad pura
  // con la causa del refresco, así que el refresco normal y el del socket no
  // pisan lo que el operador está escribiendo.
  assert.match(PAGE, /applyInterruptionMinute\(/);
  assert.doesNotMatch(
    PAGE,
    /interruptionForm\.minute = nextActiveSegment\.minute_start/,
    'the interruption minute is still overwritten on every refresh',
  );

  // El operador marca el campo al escribir (evento del input, no un `watch`).
  const minuteField = pageLineWith('v-model.number="interruptionForm.minute"');
  assert.ok(minuteField, 'the interruption minute field disappeared');
  assert.match(minuteField, /@input="markInterruptionMinuteDirty"/, 'the interruption minute has no edited marker');
  assert.match(PAGE, /function markInterruptionMinuteDirty\(\)/);
  assert.doesNotMatch(PAGE, /watch\(\s*\(\)\s*=>\s*interruptionForm\.minute/, 'a watcher marks the interruption minute');

  // Tras interrumpir con éxito se limpia: el refresco forzado vuelve a
  // prefijar y el campo no queda marcado como editado para siempre.
  const interruptBlock = PAGE.slice(
    PAGE.indexOf('async function interruptSegment'),
    PAGE.indexOf('async function assignOfficial'),
  );
  assert.ok(interruptBlock.length > 0, 'the interruption action disappeared');
  assert.match(interruptBlock, /interruptionForm\.minuteDirty = false/);
});

test('creating a segment never sends the interface flag to the server', () => {
  const createBlock = PAGE.slice(
    PAGE.indexOf('async function createSegment'),
    PAGE.indexOf('async function interruptSegment'),
  );
  assert.ok(createBlock.length > 0, 'the create-segment action disappeared');

  // El cuerpo se construye campo a campo: la bandera de interfaz no viaja.
  assert.doesNotMatch(
    createBlock,
    /\.\.\.segmentForm/,
    'the segment form is still spread into the request body',
  );
  const bodyStart = createBlock.indexOf('body:');
  assert.ok(bodyStart > 0, 'the segment request has no body');
  const body = createBlock.slice(bodyStart, createBlock.indexOf('},', bodyStart));
  assert.doesNotMatch(body, /minuteDirty/, 'the request body carries the interface flag');
  assert.match(createBlock, /segment_number: segmentForm\.segment_number/);
  assert.match(createBlock, /minute_start: segmentForm\.minute_start/);
  assert.match(createBlock, /resolutionPayload\(/);
});

// ---------------------------------------------------------------------------
// RNF-007: la propuesta se anuncia y distingue su origen
// ---------------------------------------------------------------------------

test('the proposal announces whether the minute is derived or written by the operator', () => {
  assert.equal(SEGMENT_PROPOSAL_HINT_LABEL_KEYS.derived, 'match.segmentProposalDerived');
  assert.equal(SEGMENT_PROPOSAL_HINT_LABEL_KEYS.manual, 'match.segmentProposalManual');
  assert.match(PAGE, /SEGMENT_PROPOSAL_HINT_LABEL_KEYS\[/);
  assert.match(PAGE, /segmentProposalHint\(/);

  const hint = pageLineWith("segmentProposalHintText }}");
  assert.ok(hint, 'the proposal hint is not rendered');
  assert.match(hint, /role="status"/, 'the proposal hint is not announced');
});

// ---------------------------------------------------------------------------
// RF-011: el acta cerrada se explica sin lenguaje interno
// ---------------------------------------------------------------------------

test('the closed report is announced and no writing action is offered', () => {
  const lockLine = pageLineWith("t('match.reportLocked')");
  assert.ok(lockLine, 'the closed report notice disappeared');
  assert.match(lockLine, /role="status"/, 'the closed report notice is not announced');
  assert.match(lockLine, /isTerminal/, 'the notice is not tied to a terminal match');

  // Las acciones ya deshabilitadas siguen siéndolo.
  assert.match(PAGE, /:disabled="Boolean\(busyAction\) \|\| isTerminal"/);
});

test('the report notice is product copy in both languages', () => {
  const { spanish, english } = catalogSlices();
  const internal =
    /\b(?:constituci|enmienda|amendment|engine_version|backend|payload|metadata|trigger|contrat|contract)\b/i;

  for (const key of NEW_TEXT_KEYS) {
    for (const [locale, slice] of [
      ['Spanish', spanish],
      ['English', english],
    ] as const) {
      const value = catalogValues(slice).get(key);
      assert.ok(value, `${locale} catalog has no value for ${key}`);
      assert.doesNotMatch(value, internal, `${locale} ${key} leaks internal wording`);
      // Ni un literal de producto en la pantalla ni un identificador de clave.
      assert.ok(!PAGE.includes(value), `${key} is written by hand on the screen`);
    }
  }

  const { spanish: es } = catalogSlices();
  const locked = catalogValues(es).get('match.reportLocked') ?? '';
  assert.match(locked, /no se puede editar/i, 'the notice does not say the report cannot be edited');
});

// ---------------------------------------------------------------------------
// RF-006: el 409 del cierre se explica por su código
// ---------------------------------------------------------------------------

test('closing a report explains the new 409 with its own message', () => {
  const closeBlock = PAGE.slice(PAGE.indexOf('async function closeMatch'));
  assert.ok(closeBlock.length > 0, 'the close action disappeared');
  // El clasificador de T6 decide el mensaje; el `detail` se conserva cuando la
  // causa no trae un código conocido.
  assert.match(closeBlock, /classifyCloseConflict\(cause\)/);
  assert.match(closeBlock, /closeConflictMessageKey\(/);
  assert.match(closeBlock, /actionError\.value = t\(key\)/);

  assert.equal(DOUBLE_YELLOW_INCONSISTENT_CODE, 'DOUBLE_YELLOW_INCONSISTENT');
  assert.equal(
    closeConflictMessageKey('double_yellow_inconsistent'),
    'match.doubleYellowInconsistent',
  );
});

// ---------------------------------------------------------------------------
// El alta de eventos y los textos nuevos: cableado
// ---------------------------------------------------------------------------

test('the add-event button stays wired inside the event form', () => {
  const button = pageLineWith('@click="addEvent"');
  assert.ok(button, 'the add-event button disappeared from the screen');
  assert.match(button, /\{\{ t\('match\.addEvent'\) \}\}/, 'the button lost its label');
  assert.match(button, /type="button"/, 'the add-event button is no longer a button');
  assert.equal(PAGE.split('@click="addEvent"').length - 1, 1, 'the add-event button is duplicated');

  // La acción sigue existiendo y sigue dentro del formulario del acta.
  assert.match(PAGE, /function addEvent\(\)/);
  const form = PAGE.slice(PAGE.indexOf('class="event-form"'), PAGE.indexOf('@click="addEvent"'));
  assert.ok(form.length > 0, 'the add-event button left the event form');
});

test('the new texts are declared once per language and are really used', () => {
  const { spanish, english } = catalogSlices();
  const used = extractUsedKeys(appFiles());

  for (const key of NEW_TEXT_KEYS) {
    const pattern = new RegExp(`'${key.replace(/\./g, '\\.')}':`);
    assert.match(spanish, pattern, `${key} is missing in Spanish`);
    assert.match(english, pattern, `${key} is missing in English`);
    assert.equal(spanish.split(`'${key}':`).length - 1, 1, `${key} is not declared once in Spanish`);
    assert.equal(english.split(`'${key}':`).length - 1, 1, `${key} is not declared once in English`);
    assert.ok(used.has(key), `${key} is declared but no screen uses it`);
  }
});

// ---------------------------------------------------------------------------
// RNF-007 / criterio 23: el formulario de cierre se recorre con el teclado
// ---------------------------------------------------------------------------
//
// El proyecto no tiene arnés de componentes (no hay jsdom ni
// @vue/test-utils), así que el recorrido con teclado no se puede ejecutar como
// una interacción real. Se barre la fuente del panel de cierre con las mismas
// garantías que un teclado necesita —controles nativos, etiqueta asociada,
// orden de tabulación sin `tabindex`, acción que es un `<button>` y error
// anunciado—. Es un barrido de fuente: el recorrido real con teclado del
// formulario de cierre NO está cubierto (el E2E lo rellena con `fill()`).

function closePanel(): string {
  const start = PAGE.indexOf('<section class="panel close-panel');
  assert.ok(start > 0, 'the close panel disappeared from the operation screen');
  const end = PAGE.indexOf('</section>', start);
  assert.ok(end > start, 'the close panel is not closed');
  return PAGE.slice(start, end);
}

test('every close field is a native control with its own label', () => {
  const panel = closePanel();

  // Sin controles de diseño: números y listas nativos, alcanzables con Tab.
  const inputs = panel.match(/<input\b[^>]*>/g) ?? [];
  const selects = panel.match(/<select\b[^>]*>/g) ?? [];
  const textareas = panel.match(/<textarea\b[^>]*>/g) ?? [];
  assert.ok(inputs.length >= 2, 'the regular-score fields disappeared');
  assert.ok(selects.length >= 1, 'the winner field disappeared');
  assert.ok(textareas.length >= 1, 'the administrative reason disappeared');

  for (const control of [...inputs, ...selects, ...textareas]) {
    assert.match(control, /v-model/, 'a close control is not bound to the form');
    // `tabindex` positivo rompe el orden de tabulación y uno negativo saca el
    // campo del recorrido: el formulario no usa ninguno.
    assert.doesNotMatch(control, /tabindex/i, 'a close control changes the tab order');
    assert.doesNotMatch(
      control,
      /aria-hidden="true"/,
      'a close control is hidden from assistive technology',
    );
  }

  // Cada campo va dentro de su `<label>` (o `<FormField>`, que renderiza un
  // `<label>`): el nombre accesible no depende de un `placeholder` ni de un
  // texto suelto al lado.
  const labels = (panel.match(/<label\b[^>]*>/g) ?? []).concat(panel.match(/<FormField\b[^>]*>/g) ?? []);
  assert.equal(
    labels.length,
    inputs.length + selects.length + textareas.length,
    'a close field is not wrapped by its own label',
  );
  assert.doesNotMatch(panel, /placeholder=/, 'a close field relies on placeholder text');
});

test('the close form keeps the focus order and starts the draft with the keyboard too', () => {
  const panel = closePanel();

  // El borrador local arranca al entrar con foco en el panel, sin depender del
  // ratón: el mismo `focusin` se dispara al llegar con Tab.
  assert.match(panel, /@focusin="beginClose"/, 'the close draft needs a mouse to start');

  // La acción es un `<button type="button">` nativo: se activa con Intro y con
  // Espacio, y queda deshabilitada —también para el teclado— cuando el acta no
  // admite escritura.
  const action = panel.match(/<button\b[^>]*>/g) ?? [];
  assert.equal(action.length, 1, 'the close panel must offer exactly one action');
  assert.match(action[0]!, /type="button"/, 'the close action is not a native button');
  assert.match(action[0]!, /:disabled="[^"]*isTerminal/, 'a closed report can still be submitted');
  assert.match(action[0]!, /@click="closeMatch"/, 'the close action lost its handler');

  // Ningún atajo propio: el formulario no captura teclas.
  assert.doesNotMatch(panel, /@key(?:down|up|press)/, 'the close form intercepts keys');
});

test('a rejected close is announced without moving the focus', () => {
  // El error del cierre se anuncia en una región viva y no abre un diálogo modal
  // que robe el foco del campo que el operador estaba corrigiendo.
  const line = pageLineWith('v-if="actionError" class="form-error" role="alert"');
  assert.ok(line, 'the close error is not announced');
  assert.doesNotMatch(PAGE, /<dialog|role="dialog"/, 'the close error opens a modal');
});

// ---------------------------------------------------------------------------
// Spec 016, T10 (RF-012, RF-005, RNF-007): el cierre como walkover
// ---------------------------------------------------------------------------
//
// Con la resolución prevista `walkover` el panel pide ganador y motivo, enseña
// el marcador efectivo en solo lectura y no pide segmento ni planilla. El resto
// de resoluciones conserva su formulario y su botón. Como en el resto del
// archivo, se barre la fuente: el proyecto no tiene arnés de componentes.

test('the walkover asks for a winner and a catalogue reason', () => {
  const panel = closePanel();

  // Rama propia del W.O.: ganador (el selector de siempre) y motivo nuevo.
  assert.match(panel, /v-if="resolution === 'walkover'"/, 'the walkover branch disappeared');
  assert.match(panel, /t\('match\.walkoverReason'\)/, 'the reason field disappeared');
  assert.match(
    panel,
    /v-for="option in walkoverReasonOptions"[^>]*:value="option\.value"/,
    'the reason selector does not offer the catalogue options',
  );

  // Los cuatro motivos salen de la única fuente del cliente y tienen etiqueta.
  assert.deepEqual([...WALKOVER_REASONS], ['no_show', 'withdrawal', 'insufficient_players', 'sanction']);
  for (const reason of WALKOVER_REASONS) {
    assert.match(WALKOVER_REASON_LABEL_KEYS[reason], /^match\./);
  }
  assert.match(PAGE, /walkoverReasonOptions = WALKOVER_REASONS\.map/);

  // RNF-007: el error del motivo se asocia a su selector y se anuncia.
  const reasonSelect = panel.split('\n').find((line) => line.includes("t('match.walkoverReason')"));
  assert.ok(reasonSelect, 'the reason selector is missing');
  assert.match(reasonSelect, /v-model="closeForm\.reason"/, 'the reason is not bound to the close form');
  assert.match(reasonSelect, /:aria-invalid="Boolean\(walkoverReasonError\)"/, 'the reason error is not associated');
  assert.match(reasonSelect, /:aria-describedby="walkoverReasonDescribedBy"/, 'the reason error is not described');
  assert.match(reasonSelect, /role="alert"/, 'the reason error is not announced');
  assert.match(PAGE, /WALKOVER_REASON_ERROR_ID/, 'the reason error has no id');

  // RNF-007: el ganador es el otro campo obligatorio del W.O. y su error se
  // asocia igual que el del motivo; sin ganador no basta el aviso genérico.
  const walkoverBranch = panel.slice(
    panel.indexOf("v-if=\"resolution === 'walkover'\""),
    panel.indexOf('<template v-else>'),
  );
  assert.ok(walkoverBranch.length > 0, 'the walkover branch is not delimited');
  const winnerSelect = walkoverBranch
    .split('\n')
    .find((line) => line.includes("t('match.winner')"));
  assert.ok(winnerSelect, 'the walkover winner selector is missing');
  assert.match(
    winnerSelect,
    /v-model="closeForm\.winner_team_id"/,
    'the winner is not bound to the close form',
  );
  assert.match(
    winnerSelect,
    /:aria-invalid="Boolean\(walkoverWinnerError\)"/,
    'the winner error is not associated',
  );
  assert.match(
    winnerSelect,
    /:aria-describedby="walkoverWinnerDescribedBy"/,
    'the winner error is not described',
  );
  assert.match(winnerSelect, /role="alert"/, 'the winner error is not announced');
  assert.match(
    winnerSelect,
    /:id="WALKOVER_WINNER_ERROR_ID"/,
    'the winner error has no stable id',
  );
  assert.doesNotMatch(
    winnerSelect,
    /match\.closeValidation/,
    'the winner error falls back to the generic close message',
  );

  // La pantalla resuelve el aviso con su propia clave y su id estable.
  assert.match(PAGE, /WALKOVER_WINNER_ERROR_ID = 'close-walkover-winner-error'/);
  assert.match(
    PAGE,
    /closeFieldIssue\.value\?\.key === 'match\.walkoverWinnerRequired'/,
    'the winner field does not key off its own preflight issue',
  );
});

test('the walkover shows the effective score read-only and does not send the six fields', () => {
  const panel = closePanel();

  // El marcador efectivo viene de `limits.walkover_score` y se muestra, no se
  // edita: no añade ningún control al formulario.
  assert.match(PAGE, /walkoverScore = computed\(\(\) => walkoverScoreFrom\(operationLimits\.value\)\)/);
  const scoreLine = pageLineWith("t('match.walkoverScore')");
  assert.ok(scoreLine, 'the effective walkover score is not shown');
  assert.match(scoreLine, /role="status"/, 'the effective score is not announced');
  assert.doesNotMatch(scoreLine, /<input|<select|<textarea/, 'the effective score is editable');

  // Los seis campos numéricos viven en la rama que el walkover no renderiza.
  const walkoverBranch = panel.slice(
    panel.indexOf("v-if=\"resolution === 'walkover'\""),
    panel.indexOf('<template v-else>'),
  );
  assert.ok(walkoverBranch.length > 0, 'the walkover branch is not delimited');
  for (const field of [
    'home_score_regular',
    'away_score_regular',
    'home_score',
    'away_score',
    'home_penalties',
    'away_penalties',
  ]) {
    assert.ok(
      !walkoverBranch.includes(`closeForm.${field}`),
      `the walkover still asks for ${field}`,
    );
  }

  // El cuerpo sale de la utilidad pura: en walkover no emite marcadores.
  const closeBlock = PAGE.slice(PAGE.indexOf('async function closeMatch'));
  assert.match(closeBlock, /buildCloseReportBody\(\{/, 'the close body is not built by the utility');
  assert.doesNotMatch(
    closeBlock,
    /home_score_regular: closeForm\.home_score_regular/,
    'the close body is still a literal object',
  );

  // La validación previa también es la utilidad pura, con sus dos requisitos
  // de segmento y planilla: ella decide que el W.O. no los exige.
  const validation = PAGE.slice(PAGE.indexOf('function closeValidationIssue'));
  assert.match(validation, /closePreflight\(\{/);
  assert.match(validation, /segmentActive: selectedSegmentIsActive\.value/);
  assert.match(validation, /lineupComplete: hasCompleteLineup\.value/);
  assert.match(validation, /minuteIssue:/);
 
  // D-13: el cambio a `walkover` no se bloquea por segmentos fuera del máximo.
  const change = PAGE.slice(PAGE.indexOf('function changeResolution'));
  assert.match(change, /\{ resolution: effective \}/, 'the walkover exemption is not wired');
});

test('the walkover does not need an active segment but the other resolutions still do', () => {
  const action = closePanel().split('\n').find((line) => line.includes('@click="closeMatch"'));
  assert.ok(action, 'the close action disappeared');
  assert.match(action, /isTerminal/, 'a closed report can still be submitted');
  assert.match(
    action,
    /!selectedSegmentIsActive && resolution !== 'walkover'/,
    'the active segment is still required for a walkover',
  );

  // El aviso explica por qué el botón está habilitado sin segmento ni planilla,
  // y vive dentro de la rama del walkover.
  const notice = pageLineWith("t('match.walkoverNoSegment')");
  assert.ok(notice, 'the walkover notice disappeared');
  assert.match(notice, /role="status"/, 'the walkover notice is not announced');
  assert.ok(
    PAGE.indexOf("t('match.walkoverNoSegment')") > PAGE.indexOf('v-if="resolution === \'walkover\'"'),
    'the walkover notice is outside the walkover branch',
  );
});
