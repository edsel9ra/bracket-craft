/**
 * Escenario E2E de operación y cierre (spec 012, H4-T10; RF-043, RF-045,
 * RF-050, RF-051, RF-012, RNF-005, RNF-008).
 *
 * Recorre por la interfaz, con el idioma fijado y localizadores accesibles:
 *
 * 0. **Entrada sin `?step=` (RF-013, RF-014):** la configuración se abre desde
 *    el listado, la dirección se normaliza al primer paso **sin añadir
 *    historial** y un atrás sale del asistente.
 * 1. Torneo demo, **versión publicada**: el paso de reglas es de solo lectura,
 *    muestra las cuatro modalidades y 11v11 por defecto.
 * 2. **Teclado (RF-012, RNF-005, criterio 8):** los tres asistentes se recorren
 *    **enteros** sin ratón (Tab, Home, flechas y Enter), comprobando en cada
 *    paso el foco en el título y el anuncio en la región `aria-live`; se
 *    provoca un error de validación, se comprueba que el mensaje está asociado
 *    al campo (`aria-invalid`/`aria-describedby`) y que el foco vuelve a él, se
 *    corrige y se guarda, todo con el teclado.
 * 3. Retiro lógico y reactivación en la plantilla del torneo demo, restaurada
 *    en la misma corrida.
 * 4. Un **torneo nuevo en borrador** (datos propios, sin tocar el partido ni los
 *    datos del escenario de reintento): equipos, fase, reglas con formato
 *    distinto de 11v11, mínimo de plantilla y jornada de cierre de inscripción.
 *    Aquí se ven las tres advertencias de formato y el error de límites.
 * 5. Inscripción bloqueada por tamaño: aviso local y **409** real del servidor.
 * 6. **Equivalencia del aviso de cierre con el 409 real (RF-039, criterio 13):**
 *    con la misma versión publicada, mientras la jornada de cierre no está
 *    confirmada la pantalla de plantillas no avisa y el alta responde 201;
 *    cuando la jornada queda cerrada, la pantalla avisa y el alta responde 409
 *    con el mensaje de cierre, sin código de tamaño y sin escribir la fila.
 * 7. Apertura bloqueada: el primer segmento se rechaza, no se crea ninguno y el
 *    partido sigue sin abrir.
 * 8. Cierre sin rechazo por minuto (RF-032): se publica el borrador, se inscribe
 *    un jugador por equipo, se abre el partido, se guarda la planilla, se
 *    registra un evento en el límite exacto (89 + 1 con máximo 90) y el acta se
 *    cierra sin que el servidor la rechace por minuto.
 *
 * El escenario escribe **su** artefacto (`view-operation-flow.json`), su traza
 * sin cabeceras y, solo si el veredicto no es verde, una captura. No comparte
 * spec, localizadores ni veredicto con el escenario de reintento. Todas las
 * esperas son por condición observable: no hay esperas fijas ni reintentos.
 */

import { expect, type Locator, type Page } from '@playwright/test';

import {
  captureScreenshot,
  reportPath,
  traceConsole,
  traceFileName,
  traceNavigation,
  tracePageError,
  writeJsonReport,
  writeTrace,
  type TraceEntry,
} from './artifacts.ts';
import { E2E_LABELS, labelText } from './labels.ts';
import { MAX_MS, shouldCaptureScreenshot } from './observations.ts';
import {
  OPERATION_FLOW_VIEW,
  buildOperationFlowArtifact,
  type OperationFlowArtifact,
  type OperationFlowSample,
  type OperationFlowState,
  type OperationFlowVerdict,
} from './operationFlowModel.ts';

const HYDRATION_TIMEOUT_MS = 120_000;

/**
 * Tope de pulsaciones de Tab para alcanzar un control desde el principio del
 * documento. No es una espera: el bucle corta en cuanto el foco llega.
 */
const KEYBOARD_TAB_LIMIT = 320;

/** Jornada del cierre de inscripción que configura este escenario. */
const LOCK_MATCHDAY = '1';

/** `detail` con el que el servidor rechaza el alta con el cierre activo. */
const ROSTER_LOCK_SERVER_DETAIL = `La plantilla está cerrada desde la jornada ${LOCK_MATCHDAY}`;

/**
 * Paso del asistente: identificador (el valor de `?step=`) y texto visible.
 * El identificador permite esperar la dirección, que es la condición
 * observable de que el cambio de paso terminó (RF-013).
 */
interface WizardStepTarget {
  readonly id: string;
  readonly label: string;
}

const RULES_STEPS: readonly WizardStepTarget[] = [
  { id: 'rules.scoring', label: E2E_LABELS.rulesStepScoring },
  { id: 'rules.tiebreakers', label: E2E_LABELS.rulesStepTiebreakers },
  { id: 'rules.discipline', label: E2E_LABELS.rulesStepDiscipline },
  { id: 'rules.resolution', label: E2E_LABELS.rulesStepResolution },
  { id: 'rules.format', label: E2E_LABELS.rulesStepFormat },
  { id: 'rules.substitutions', label: E2E_LABELS.rulesStepSubstitutions },
  { id: 'rules.registration', label: E2E_LABELS.rulesStepRegistration },
  { id: 'rules.overrides', label: E2E_LABELS.rulesStepOverrides },
].map(({ id, label }) => ({ id, label: labelText(label) }));

const PHASES_STEPS: readonly WizardStepTarget[] = [
  { id: 'phases.identity', label: E2E_LABELS.phasesStepIdentity },
  { id: 'phases.composition', label: E2E_LABELS.phasesStepComposition },
  { id: 'phases.review', label: E2E_LABELS.phasesStepReview },
].map(({ id, label }) => ({ id, label: labelText(label) }));

const TEAMS_STEPS: readonly WizardStepTarget[] = [
  { id: 'teams.details', label: E2E_LABELS.teamsStepDetails },
  { id: 'teams.individual', label: E2E_LABELS.teamsStepIndividual },
  { id: 'teams.bulk', label: E2E_LABELS.teamsStepBulk },
  { id: 'teams.review', label: E2E_LABELS.teamsStepReview },
].map(({ id, label }) => ({ id, label: labelText(label) }));

const FLOW_STAGE = 'Fase E2E';
const BLOCKED_STAGE = 'Fase bloqueada E2E';

/**
 * Equipos del torneo de prueba. El nombre y el código llevan el sufijo de la
 * corrida porque los equipos son de la **organización** y no del torneo: así
 * una segunda ejecución local no choca con los equipos que dejó la anterior.
 */
function flowTeamsFor(suffix: string): readonly { name: string; shortCode: string }[] {
  return [
    { name: `Límites ${suffix} FC`, shortCode: `L${suffix.slice(-4)}` },
    { name: `Frontera ${suffix} FC`, shortCode: `F${suffix.slice(-4)}` },
  ];
}

function flowCsvFor(teams: readonly { name: string; shortCode: string }[]): string {
  return ['name,short_code,logo_url', ...teams.map((team) => `${team.name},${team.shortCode},`)].join(
    '\n',
  );
}

/** Fallo con veredicto explícito; el borde lo convierte en artefacto. */
class OperationFlowFailure extends Error {
  readonly verdict: OperationFlowVerdict;
  readonly cause: string;

  constructor(verdict: OperationFlowVerdict, cause: string) {
    super(cause);
    this.name = 'OperationFlowFailure';
    this.verdict = verdict;
    this.cause = cause;
  }
}

export interface OperationFlowInput {
  readonly page: Page;
  readonly tournamentId: string;
}

export interface OperationFlowResult {
  readonly artifact: OperationFlowArtifact;
  readonly artifactPath: string;
}

function describeError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Señal de hidratación ya declarada por el arnés: Vue montado en `#__nuxt`.
 * Se duplica aquí para no importar `session.setup.ts`, cuyo registro de test
 * se ejecutaría también en este proyecto.
 */
async function waitForHydration(page: Page): Promise<void> {
  await page.waitForFunction(
    () => {
      const container = document.querySelector('#__nuxt');
      return container !== null && '__vue_app__' in container;
    },
    undefined,
    { timeout: HYDRATION_TIMEOUT_MS },
  );
}

async function open(page: Page, path: string): Promise<void> {
  await page.goto(path, { waitUntil: 'load', timeout: MAX_MS.initialConnected });
  await waitForHydration(page);
}

/**
 * Abre una dirección y espera a que la carga de datos de la página termine.
 * La comprobación de hidratación sola no basta: la página vuelve a pedir sus
 * datos al hidratar y puede reemplazar el DOM después de la primera escritura.
 * `networkidle` es una condición observable (sin red pendiente), no una espera
 * fija.
 */
async function openSettled(page: Page, path: string): Promise<void> {
  await open(page, path);
  await page.waitForLoadState('networkidle', { timeout: MAX_MS.initialConnected });
}

function sectionFor(page: Page, heading: string): Locator {
  return page
    .locator('section.wizard-shell')
    .filter({ has: page.getByRole('heading', { name: heading, exact: true }) })
    .first();
}

/** Panel del acta de partido: eventos, planilla y cierre (RF-032). */
function reportPanel(page: Page): Locator {
  return page
    .locator('section.panel')
    .filter({
      has: page.getByRole('heading', {
        name: labelText(E2E_LABELS.operationReportHeading),
        exact: true,
      }),
    })
    .first();
}

function stepButtons(page: Page, wizard: Locator): Locator {
  return wizard
    .getByRole('navigation', { name: labelText(E2E_LABELS.wizardIndex), exact: true })
    .getByRole('button');
}

/**
 * Nombre accesible **por prefijo**. Un `<label>` que envuelve a un `<select>`
 * incluye en su nombre las opciones visibles, así que el nombre accesible del
 * control es «Versión v1 · Publicado» y no «Versión». El prefijo sigue anclado
 * al texto declarado y no depende de la opción seleccionada.
 */
function namePattern(label: string): RegExp {
  return new RegExp(`^${escapeRegExp(label)}`);
}

/**
 * Selecciona una opción de un `<select>` por un fragmento de su texto visible.
 * No depende del orden ni del identificador de la opción.
 */
async function selectOptionContaining(select: Locator, needle: string): Promise<void> {
  const value = await select.locator('option').evaluateAll((options, text) => {
    const match = options.find((option) => (option.textContent ?? '').includes(text));
    return match ? (match as HTMLOptionElement).value : '';
  }, needle);
  if (!value) {
    throw new OperationFlowFailure(
      'infrastructure',
      `no se encontró la opción «${needle}» en el selector`,
    );
  }
  await select.selectOption(value);
}

async function clickStep(page: Page, wizard: Locator, stepLabel: string): Promise<void> {
  const buttons = stepButtons(page, wizard);
  const texts = (await buttons.allTextContents()).map((text) => text.replace(/\s+/g, ' '));
  const index = texts.findIndex((text) => text.includes(stepLabel));
  if (index < 0) {
    throw new OperationFlowFailure('infrastructure', `el asistente no declara el paso «${stepLabel}»`);
  }
  await buttons.nth(index).click();
}

/**
 * Abre un paso con el ratón y espera a que el cambio termine. Si el paso ya era
 * el vigente no hay navegación: se espera solo a que el índice lo marque, porque
 * la dirección conserva entonces el paso de otro asistente.
 */
async function clickStepAndSettle(
  page: Page,
  wizard: Locator,
  steps: readonly WizardStepTarget[],
  index: number,
  cause: string,
): Promise<void> {
  const step = steps[index];
  if (!step) {
    throw new OperationFlowFailure('behavioral', `${cause}: el paso ${index} no existe`);
  }
  const buttons = stepButtons(page, wizard);
  const before = await buttons.evaluateAll((elements) => (
    elements.findIndex((element) => element.getAttribute('aria-current') === 'step')
  ));
  await clickStep(page, wizard, step.label);
  await expect(buttons.nth(index)).toHaveAttribute('aria-current', 'step');
  if (before !== index) await expectStepUrl(page, step.id);
}

/** Entra en el índice de pasos con Tab desde el principio del documento. */
async function enterStepIndex(page: Page, wizard: Locator, cause: string): Promise<void> {
  const buttons = stepButtons(page, wizard);
  await expect(buttons.first()).toBeVisible({ timeout: MAX_MS.initialConnected });
  await tabUntilFocused(page, buttons.first(), cause);
}

/** Espera a que la dirección refleje el paso: condición de fin del cambio (RF-013). */
async function expectStepUrl(page: Page, stepId: string): Promise<void> {
  await expect
    .poll(
      () => new URL(page.url()).searchParams.get('step'),
      { timeout: MAX_MS.initialConnected },
    )
    .toBe(stepId);
}

/**
 * Abre un paso con el teclado desde el principio del documento (Tab, Home,
 * flechas y Enter). Se usa al entrar en una página recién cargada.
 */
async function keyboardOpenStepFromTop(
  page: Page,
  wizard: Locator,
  step: WizardStepTarget,
  index: number,
  cause: string,
): Promise<void> {
  const buttons = stepButtons(page, wizard);
  await enterStepIndex(page, wizard, cause);
  await page.keyboard.press('Home');
  for (let move = 0; move < index; move += 1) {
    await page.keyboard.press('ArrowDown');
  }
  await expect(buttons.nth(index)).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(wizard.locator('h3.wizard-step-title')).toBeFocused();
  await expectStepUrl(page, step.id);
}

/** Entra en el índice de pasos con Shift+Tab, desde el título o desde el cuerpo. */
async function focusStepIndex(page: Page, wizard: Locator, cause: string): Promise<void> {
  const buttons = stepButtons(page, wizard);
  for (let attempt = 0; attempt < 8; attempt += 1) {
    const inside = await buttons.evaluateAll((elements) => (
      elements.includes(document.activeElement as HTMLElement)
    ));
    if (inside) return;
    await page.keyboard.press('Shift+Tab');
  }
  throw new OperationFlowFailure(
    'behavioral',
    `${cause}: el foco no volvió al índice de pasos con Shift+Tab`,
  );
}

/**
 * Llega al paso indicado **con el teclado** desde el índice: Home y flechas
 * mueven el foco y Enter lo activa. Después comprueba que el foco está en el
 * título del paso.
 */
async function keyboardGoToStep(
  page: Page,
  wizard: Locator,
  index: number,
  steps: readonly WizardStepTarget[],
  cause: string,
): Promise<void> {
  const buttons = stepButtons(page, wizard);
  const target = steps[index];
  if (!target) {
    throw new OperationFlowFailure('behavioral', `${cause}: el paso ${index} no existe`);
  }
  await focusStepIndex(page, wizard, cause);
  await page.keyboard.press('Home');
  for (let move = 0; move < index; move += 1) {
    await page.keyboard.press('ArrowDown');
  }
  await expect(buttons.nth(index)).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(wizard.locator('h3.wizard-step-title')).toBeFocused();
  await expectStepUrl(page, target.id);
}

async function isFocused(locator: Locator): Promise<boolean> {
  return locator
    .evaluate((element) => element === element.ownerDocument.activeElement)
    .catch(() => false);
}

/** Avanza con Tab hasta que el control recibe el foco; nunca usa el ratón. */
async function tabUntilFocused(page: Page, target: Locator, cause: string): Promise<void> {
  for (let attempt = 0; attempt < KEYBOARD_TAB_LIMIT; attempt += 1) {
    if (await isFocused(target)) return;
    await page.keyboard.press('Tab');
  }
  if (!(await isFocused(target))) {
    throw new OperationFlowFailure('behavioral', `${cause}: «Tab» no llegó al control`);
  }
}

/**
 * Recorre **todos** los pasos del asistente solo con teclado: Tab para entrar
 * en el índice, Home y flechas para moverse y Enter para activar. En cada paso
 * comprueba que el foco llega al título y que el cambio se anuncia en la región
 * `aria-live`. Si el paso vigente es el primero, activa antes el segundo: así
 * cada activación es un cambio real y siempre mueve el foco.
 */
async function traverseWizardByKeyboard(
  page: Page,
  wizard: Locator,
  steps: readonly WizardStepTarget[],
  cause: string,
): Promise<void> {
  const buttons = stepButtons(page, wizard);
  const count = await buttons.count();
  if (count !== steps.length) {
    throw new OperationFlowFailure(
      'behavioral',
      `${cause}: el asistente declara ${count} pasos y se esperaban ${steps.length}`,
    );
  }

  const current = await buttons.evaluateAll((elements) => (
    elements.findIndex((element) => element.getAttribute('aria-current') === 'step')
  ));
  await enterStepIndex(page, wizard, cause);
  let fromTitle = false;
  const firstAlternate = steps[1];
  if (current === 0 && count > 1 && firstAlternate) {
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    await expect(wizard.locator('h3.wizard-step-title')).toHaveText(firstAlternate.label);
    await expectStepUrl(page, firstAlternate.id);
    fromTitle = true;
  }

  for (let index = 0; index < count; index += 1) {
    const step = steps[index];
    if (!step) {
      throw new OperationFlowFailure('behavioral', `${cause}: el paso ${index} no existe`);
    }
    if (fromTitle) {
      // Desde el título del paso anterior, Shift+Tab vuelve al índice.
      await page.keyboard.press('Shift+Tab');
      await expect(buttons.last()).toBeFocused();
      fromTitle = false;
    }
    await page.keyboard.press('Home');
    for (let move = 0; move < index; move += 1) {
      await page.keyboard.press('ArrowDown');
    }
    await expect(buttons.nth(index)).toBeFocused();
    await page.keyboard.press('Enter');
    const title = wizard.locator('h3.wizard-step-title');
    await expect(title).toBeFocused();
    await expect(title).toHaveText(step.label);
    await expect(wizard.locator('[aria-live="polite"]')).toContainText(step.label);
    // La dirección es la condición de fin: sin esperarla, el cambio de paso
    // siguiente competiría con la navegación pendiente del anterior.
    await expectStepUrl(page, step.id);
    fromTitle = true;
  }
}

/** Sustituye los marcadores `{nombre}` de una etiqueta del catálogo. */
function fillLabel(template: string, values: Readonly<Record<string, string>>): string {
  return Object.entries(values).reduce(
    (text, [key, value]) => text.split(`{${key}}`).join(value),
    template,
  );
}

/**
 * Fecha futura para el partido del escenario. La fecha no puede ser anterior al
 * ``eligible_from`` de las plantillas que el propio escenario crea al vuelo: una
 * fecha fija hacía fallar la planilla (422 «aún no elegible») en cualquier
 * corrida posterior a esa hora.
 */
function futureMatchDateLocal(): string {
  const date = new Date(Date.now() + 2 * 24 * 60 * 60 * 1000);
  const pad = (value: number): string => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T12:00`;
}

function formatCount(template: string, count: number): string {
  return template.replace('{count}', String(count));
}

export async function runOperationFlow(input: OperationFlowInput): Promise<OperationFlowResult> {
  const { page, tournamentId } = input;
  const startedAt = Date.now();
  const samples: OperationFlowSample[] = [];
  const trace: TraceEntry[] = [];
  const runSuffix = String(Date.now());
  const tournamentName = `Copa E2E ${runSuffix}`;
  const flowTeams = flowTeamsFor(runSuffix);
  const flowCsv = flowCsvFor(flowTeams);
  const [homeTeam, awayTeam] = flowTeams;
  if (!homeTeam || !awayTeam) {
    throw new OperationFlowFailure('infrastructure', 'no se generaron los dos equipos de prueba');
  }

  const record = (status: OperationFlowState): void => {
    samples.push({ status, at: Date.now() });
  };

  const onConsole = (message: { type(): string; text(): string }): void => {
    trace.push(traceConsole({ at: Date.now(), level: message.type(), text: message.text() }));
  };
  const onPageError = (error: Error): void => {
    trace.push(tracePageError({ at: Date.now(), text: error.message }));
  };
  const onNavigation = (frame: { url(): string }): void => {
    trace.push(traceNavigation({ at: Date.now(), url: frame.url() }));
  };

  /** Envuelve una comprobación de producto: su fallo es de comportamiento. */
  const check = async (cause: string, callback: () => Promise<void>): Promise<void> => {
    try {
      await callback();
    } catch (error) {
      throw new OperationFlowFailure('behavioral', `${cause}: ${describeError(error)}`);
    }
  };

  let failure: OperationFlowFailure | null = null;

  const finalize = async (
    verdict: OperationFlowVerdict,
    cause: string | null,
  ): Promise<OperationFlowResult> => {
    const artifact = buildOperationFlowArtifact({
      verdict,
      cause,
      durationMs: Date.now() - startedAt,
      states: samples,
    });
    const artifactPath = await writeJsonReport(`view-${OPERATION_FLOW_VIEW}.json`, artifact);
    await writeTrace(
      [...trace].sort((left, right) => left.at - right.at),
      traceFileName(OPERATION_FLOW_VIEW),
    );
    if (shouldCaptureScreenshot(verdict)) {
      await captureScreenshot(page, OPERATION_FLOW_VIEW).catch(() => '');
    }
    return { artifact, artifactPath };
  };

  try {
    page.on('console', onConsole);
    page.on('pageerror', onPageError);
    page.on('framenavigated', (frame) => {
      if (frame === page.mainFrame()) onNavigation(frame);
    });

    // ------------------------------------------------------------------
    // 0. Entrada sin `?step=` (RF-013, RF-014): la configuración se abre desde
    //    el listado y la dirección se normaliza al paso de entrada **sin
    //    añadir historial** (+0 por la normalización); un atrás desde ahí sale
    //    del asistente y el paso mostrado coincide con `aria-current`.
    // ------------------------------------------------------------------
    const rulesWizard = sectionFor(page, labelText(E2E_LABELS.rulesWizard));
    await openSettled(page, '/workspace');
    await check('entrada-sin-paso-normalizada', async () => {
      const entry = RULES_STEPS[0];
      if (!entry) {
        throw new OperationFlowFailure('infrastructure', 'el asistente de reglas no declara pasos');
      }
      const configure = page
        .locator(`a[href="/workspace/tournaments/${tournamentId}"]`)
        .first();
      await expect(configure).toBeVisible({ timeout: MAX_MS.initialConnected });

      const historyBefore = await page.evaluate(() => window.history.length);
      await configure.click();
      await expectStepUrl(page, entry.id);
      // La normalización usa `replace`: no añade ninguna entrada. La única
      // entrada nueva es la de la navegación al abrir la configuración.
      const historyAfter = await page.evaluate(() => window.history.length);
      if (historyAfter !== historyBefore + 1) {
        throw new OperationFlowFailure(
          'behavioral',
          `la normalización añadió ${historyAfter - historyBefore - 1} entradas de historial de más`,
        );
      }

      const buttons = stepButtons(page, rulesWizard);
      await expect(rulesWizard.locator('h3.wizard-step-title')).toHaveText(entry.label);
      await expect(buttons.nth(0)).toHaveAttribute('aria-current', 'step');
      await expect(buttons.nth(1)).not.toHaveAttribute('aria-current', 'step');

      // Atrás: sale del asistente al listado, no a otro paso.
      await page.goBack();
      await expect(page).toHaveURL(/\/workspace$/);
      await expect(page.locator('section.wizard-shell')).toHaveCount(0);
    });
    record('wizard-entry-normalized');

    // ------------------------------------------------------------------
    // 1. Versión publicada del torneo demo: solo lectura y formato por
    //    defecto. No se crea ningún borrador sobre un torneo en operación.
    // ------------------------------------------------------------------
    await open(page, `/workspace/tournaments/${encodeURIComponent(tournamentId)}`);

    const versionSelect = page
      .getByRole('combobox', { name: namePattern(labelText(E2E_LABELS.versionField)) })
      .first();
    await check('version-publicada-disponible', async () => {
      await expect(versionSelect.locator('option').first()).toBeAttached({
        timeout: MAX_MS.initialConnected,
      });
      await selectOptionContaining(versionSelect, 'Publicado');
    });

    await check('reglas-solo-lectura', async () => {
      await expect(
        rulesWizard.getByText(labelText(E2E_LABELS.wizardReadOnly), { exact: true }),
      ).toBeVisible();
      await expect(
        rulesWizard.getByRole('button', {
          name: labelText(E2E_LABELS.saveRules),
          exact: true,
        }),
      ).toHaveCount(0);
    });
    record('rules-read-only');

    await check('formato-por-defecto', async () => {
      // El paso se abre con el teclado desde el principio del documento.
      const formatStep = RULES_STEPS[4];
      if (!formatStep) throw new OperationFlowFailure('infrastructure', 'sin paso de formato');
      await keyboardOpenStepFromTop(page, rulesWizard, formatStep, 4, 'formato-por-defecto');
      const formatSelect = rulesWizard.getByRole('combobox', {
        name: namePattern(labelText(E2E_LABELS.gameFormatField)),
      });
      await expect(formatSelect.locator('option')).toHaveCount(4);
      await expect(formatSelect.locator('option').nth(0)).toHaveText('5v5');
      await expect(formatSelect.locator('option').nth(1)).toHaveText('7v7');
      await expect(formatSelect.locator('option').nth(2)).toHaveText('9v9');
      await expect(formatSelect.locator('option').nth(3)).toHaveText('11v11');
      await expect(formatSelect).toHaveValue('11v11');
    });
    record('rules-format-default');

    // ------------------------------------------------------------------
    // 2. Retiro lógico y reactivación en la plantilla del torneo demo.
    //    Se llega por el enlace del índice (navegación de cliente) para que los
    //    controles ya estén hidratados; el estado se restaura en esta corrida.
    // ------------------------------------------------------------------
    await page
      .getByRole('navigation', { name: labelText(E2E_LABELS.tournamentNav), exact: true })
      .getByRole('link', { name: labelText(E2E_LABELS.navRosters), exact: true })
      .click();
    await expect(
      page.getByRole('heading', { name: labelText(E2E_LABELS.rostersTitle), exact: true }),
    ).toBeVisible({ timeout: MAX_MS.initialConnected });

    await check('estado-de-plantilla-restaurado', async () => {
      const stale = page.getByRole('button', {
        name: labelText(E2E_LABELS.rosterReactivate),
        exact: true,
      });
      while ((await stale.count()) > 0) {
        await stale.first().click();
        await expect(
          page.getByText(labelText(E2E_LABELS.rosterReactivatedNotice), { exact: true }),
        ).toBeVisible();
      }
    });

    await check('retiro-logico', async () => {
      const retire = page
        .getByRole('button', { name: labelText(E2E_LABELS.rosterRetire), exact: true })
        .first();
      await expect(retire).toBeVisible({ timeout: MAX_MS.initialConnected });
      await retire.click();
      await expect(
        page.getByText(labelText(E2E_LABELS.rosterRetiredNotice), { exact: true }),
      ).toBeVisible();
      await expect(
        page.getByText(labelText(E2E_LABELS.rosterStateRetired), { exact: true }),
      ).toHaveCount(1);
    });
    record('roster-retired');

    await check('reactivacion', async () => {
      const reactivate = page
        .getByRole('button', { name: labelText(E2E_LABELS.rosterReactivate), exact: true })
        .first();
      await expect(reactivate).toBeVisible();
      await reactivate.click();
      await expect(
        page.getByText(labelText(E2E_LABELS.rosterReactivatedNotice), { exact: true }),
      ).toBeVisible();
      await expect(
        page.getByText(labelText(E2E_LABELS.rosterStateRetired), { exact: true }),
      ).toHaveCount(0);
    });
    record('roster-reactivated');

    // Volver al Workspace por la navegación principal (cliente).
    await page
      .getByRole('navigation', { name: labelText(E2E_LABELS.primaryNav), exact: true })
      .getByRole('link', { name: labelText(E2E_LABELS.tournamentsNav), exact: true })
      .first()
      .click();
    await expect(
      page.getByRole('button', { name: labelText(E2E_LABELS.newTournament), exact: true }),
    ).toBeVisible({ timeout: MAX_MS.initialConnected });


    // ------------------------------------------------------------------
    // 4. Torneo nuevo en borrador: datos propios, sin tocar el torneo demo.
    // ------------------------------------------------------------------
    await check('torneo-borrador-creado', async () => {
      await page
        .getByRole('button', { name: labelText(E2E_LABELS.newTournament), exact: true })
        .click();
      const nameInput = page.getByRole('textbox', {
        name: namePattern(labelText(E2E_LABELS.workspaceName)),
      });
      await expect(nameInput).toBeVisible();
      await nameInput.fill(tournamentName);
      await page
        .getByRole('textbox', { name: namePattern(labelText(E2E_LABELS.seasonField)) })
        .fill('2026');
      await page
        .getByLabel(namePattern(labelText(E2E_LABELS.startField)))
        .fill('2026-01-01');
      await page
        .getByRole('button', {
          name: labelText(E2E_LABELS.createDraftTournament),
          exact: true,
        })
        .click();
      const card = page
        .locator('article')
        .filter({
          has: page.getByRole('heading', { name: new RegExp(escapeRegExp(tournamentName)) }),
        })
        .first();
      const link = card.getByRole('link', {
        name: new RegExp(escapeRegExp(labelText(E2E_LABELS.workspaceConfigure))),
      });
      await expect(link).toBeVisible({ timeout: MAX_MS.initialConnected });
      await link.click();
      await expect(
        versionSelect.locator('option').filter({ hasText: 'Borrador' }),
      ).toHaveCount(1, { timeout: MAX_MS.initialConnected });
    });

    const tournamentMatch = /\/workspace\/tournaments\/([^/?#]+)/.exec(page.url());
    const flowTournamentId = tournamentMatch ? decodeURIComponent(tournamentMatch[1] ?? '') : '';
    if (!flowTournamentId) {
      throw new OperationFlowFailure('infrastructure', 'no se pudo identificar el torneo nuevo');
    }

    // 3a. Equipos propios (alta masiva por la interfaz). Cada cambio de paso se
    //     espera por la dirección: es la condición de fin del cambio (RF-013) y
    //     evita que la navegación anterior revierta el paso siguiente.
    const teamsWizard = sectionFor(page, labelText(E2E_LABELS.teamsWizard));
    await check('equipos-creados', async () => {
      await teamsWizard
        .getByRole('textbox', { name: namePattern(labelText(E2E_LABELS.workspaceName)) })
        .fill('Copa E2E');
      await teamsWizard
        .getByRole('textbox', { name: namePattern(labelText(E2E_LABELS.teamCodeField)) })
        .fill('CEE');
      const next = teamsWizard.getByRole('button', {
        name: labelText(E2E_LABELS.wizardNext),
        exact: true,
      });
      await next.click();
      await expectStepUrl(page, 'teams.individual');
      await teamsWizard
        .getByRole('radio', { name: labelText(E2E_LABELS.teamPathBulk), exact: true })
        .check();
      // Elegir la vía ya muestra su paso (RF-011), así que no se avanza otra vez:
      // un «Siguiente» adicional llevaría a la revisión sin pasar por el CSV.
      await expectStepUrl(page, 'teams.bulk');
      await teamsWizard
        .getByRole('textbox', { name: namePattern(labelText(E2E_LABELS.teamCsvField)) })
        .fill(flowCsv);
      await next.click();
      await expectStepUrl(page, 'teams.review');
      await teamsWizard
        .getByRole('button', { name: labelText(E2E_LABELS.teamsConfirm), exact: true })
        .click();
      await expect(
        teamsWizard.getByText(formatCount(labelText(E2E_LABELS.teamsCreatedBulk), 2), {
          exact: false,
        }),
      ).toBeVisible({ timeout: MAX_MS.initialConnected });
    });

    // 3b. Fase con los dos equipos, sin límites todavía.
    const phasesWizard = sectionFor(page, labelText(E2E_LABELS.phasesWizard));
    await check('fase-creada', async () => {
      const modeSelect = phasesWizard.getByRole('combobox', {
        name: namePattern(labelText(E2E_LABELS.stageModeField)),
      });
      await modeSelect.selectOption('create');
      await clickStepAndSettle(page, phasesWizard, PHASES_STEPS, 0, 'identidad-de-la-fase');
      await phasesWizard
        .getByRole('textbox', { name: namePattern(labelText(E2E_LABELS.workspaceName)) })
        .fill(FLOW_STAGE);
      // El orden se fija para que esta fase sea la primera de la versión: el
      // cierre de inscripción mira la jornada de la primera fase.
      await phasesWizard
        .getByRole('spinbutton', { name: namePattern(labelText(E2E_LABELS.stageOrderField)) })
        .fill('1');
      const next = phasesWizard.getByRole('button', {
        name: labelText(E2E_LABELS.wizardNext),
        exact: true,
      });
      await next.click();
      await expectStepUrl(page, 'phases.composition');
      const boxes = phasesWizard.getByRole('checkbox');
      await expect(boxes).toHaveCount(2);
      for (let index = 0; index < 2; index += 1) await boxes.nth(index).check();
      await next.click();
      await expectStepUrl(page, 'phases.review');
      await phasesWizard
        .getByRole('button', { name: labelText(E2E_LABELS.stageConfirmCreate), exact: true })
        .click();
      await expect(
        phasesWizard.getByText(labelText(E2E_LABELS.stageCreatedAndAssigned), { exact: false }),
      ).toBeVisible({ timeout: MAX_MS.initialConnected });
    });

    // 3c. Teclado (RF-012, RNF-005, criterio 8): recorrido completo de los tres
    //     asistentes con Tab, Home, flechas y Enter; error de límites anunciado
    //     y asociado a su campo, corrección y guardado, todo sin ratón.
    const configurationUrl = `/workspace/tournaments/${encodeURIComponent(flowTournamentId)}`;

    await check('teclado-reglas-todos-los-pasos', async () => {
      await openSettled(page, configurationUrl);
      await traverseWizardByKeyboard(page, rulesWizard, RULES_STEPS, 'teclado-reglas');
    });
    record('wizard-keyboard-rules');

    await check('jornada-de-cierre-configurada', async () => {
      await keyboardGoToStep(page, rulesWizard, 6, RULES_STEPS, 'jornada-de-cierre');
      const lockField = rulesWizard.getByRole('spinbutton', {
        name: namePattern(labelText(E2E_LABELS.rosterLockField)),
      });
      await tabUntilFocused(page, lockField, 'jornada-de-cierre');
      await page.keyboard.press('Control+a');
      await page.keyboard.type(LOCK_MATCHDAY);
      await expect(lockField).toHaveValue(LOCK_MATCHDAY);
      await page.keyboard.press('Tab');
    });

    await check('formato-distinto-y-advertencia-reglas', async () => {
      await keyboardGoToStep(page, rulesWizard, 4, RULES_STEPS, 'formato-y-limites');
      const formatSelect = rulesWizard.getByRole('combobox', {
        name: namePattern(labelText(E2E_LABELS.gameFormatField)),
      });
      await tabUntilFocused(page, formatSelect, 'formato-y-limites');
      await page.keyboard.press('Home');
      await page.keyboard.press('ArrowDown');
      await page.keyboard.press('Tab');
      await expect(formatSelect).toHaveValue('7v7');
      await expect(rulesWizard.getByText('Formato 7v7 · alineación sin esquema táctico', { exact: true })).toBeVisible();
    });
    record('rules-format-warning');

    await check('error-de-limites-asociado', async () => {
      const minInput = rulesWizard.getByRole('spinbutton', {
        name: namePattern(labelText(E2E_LABELS.minPlayersField)),
      });
      const maxInput = rulesWizard.getByRole('spinbutton', {
        name: namePattern(labelText(E2E_LABELS.maxPlayersField)),
      });
      // El foco llega al campo con Tab; el valor se escribe con el teclado.
      await tabUntilFocused(page, minInput, 'error-de-limites');
      await page.keyboard.press('Control+a');
      await page.keyboard.type('10');
      await page.keyboard.press('Tab');
      await expect(maxInput).toBeFocused();
      await page.keyboard.press('Control+a');
      await page.keyboard.type('5');
      await page.keyboard.press('Tab');

      const message = rulesWizard
        .getByRole('alert')
        .filter({ hasText: labelText(E2E_LABELS.rosterLimitsPairError) });
      await expect(message).toBeVisible();
      await expect(maxInput).toHaveAttribute('aria-invalid', 'true');
      const messageId = (await message.getAttribute('id')) ?? '';
      const describedBy = (await maxInput.getAttribute('aria-describedby')) ?? '';
      if (!messageId || !describedBy.split(/\s+/).includes(messageId)) {
        throw new OperationFlowFailure(
          'behavioral',
          `error-de-limites: el mensaje «${messageId || 'sin id'}» no está asociado al campo `
            + `(aria-describedby: «${describedBy || 'ausente'}»)`,
        );
      }
      // El mensaje se alcanza con el teclado: Shift+Tab devuelve el foco al campo.
      await page.keyboard.press('Shift+Tab');
      await expect(maxInput).toBeFocused();
      const formatStep = stepButtons(page, rulesWizard).filter({
        hasText: labelText(E2E_LABELS.rulesStepFormat),
      });
      await expect(formatStep.first()).toContainText(labelText(E2E_LABELS.wizardStateError));
    });
    record('wizard-error-associated');

    await check('error-de-limites-corregido', async () => {
      const minInput = rulesWizard.getByRole('spinbutton', {
        name: namePattern(labelText(E2E_LABELS.minPlayersField)),
      });
      const maxInput = rulesWizard.getByRole('spinbutton', {
        name: namePattern(labelText(E2E_LABELS.maxPlayersField)),
      });
      await expect(maxInput).toBeFocused();
      await page.keyboard.press('Control+a');
      await page.keyboard.type('0');
      await page.keyboard.press('Shift+Tab');
      await expect(minInput).toBeFocused();
      await page.keyboard.press('Control+a');
      await page.keyboard.type('1');
      await page.keyboard.press('Tab');
      await expect(rulesWizard.getByRole('alert')).toHaveCount(0);
      await expect(maxInput).not.toHaveAttribute('aria-invalid', 'true');
      const formatStep = stepButtons(page, rulesWizard).filter({
        hasText: labelText(E2E_LABELS.rulesStepFormat),
      });
      await expect(formatStep.first()).toContainText(labelText(E2E_LABELS.wizardStateComplete));
    });
    record('wizard-error-corrected');

    await check('reglas-guardadas', async () => {
      const save = rulesWizard.getByRole('button', {
        name: labelText(E2E_LABELS.saveRules),
        exact: true,
      });
      await tabUntilFocused(page, save, 'guardar-reglas');
      await expect(save).toBeEnabled();
      await page.keyboard.press('Enter');
      await expect(page.locator('#resumen').getByText('Formato 7v7 · alineación sin esquema táctico', { exact: true })).toBeVisible({ timeout: MAX_MS.initialConnected });
      await expect(page.locator('#resumen')).toContainText('7v7');
    });
    record('rules-saved');
    record('summary-format-warning');

    await check('teclado-fases-todos-los-pasos', async () => {
      await openSettled(page, configurationUrl);
      await traverseWizardByKeyboard(page, phasesWizard, PHASES_STEPS, 'teclado-fases');
    });
    record('wizard-keyboard-phases');

    await check('teclado-equipos-todos-los-pasos', async () => {
      await openSettled(page, configurationUrl);
      await traverseWizardByKeyboard(page, teamsWizard, TEAMS_STEPS, 'teclado-equipos');
    });
    record('wizard-keyboard-teams');

    // ------------------------------------------------------------------
    // 4b. Atrás (RF-019, criterio 14): la dirección es la única fuente del paso.
    //     Se entra al asistente desde otra pantalla, se avanza un paso y un solo
    //     «atrás» devuelve al paso anterior —dirección, título y `aria-current`
    //     coinciden—; el segundo «atrás» sale del asistente.
    // ------------------------------------------------------------------
    await check('atras-vuelve-al-paso-anterior', async () => {
      const [firstStep, secondStep] = RULES_STEPS;
      if (!firstStep || !secondStep) {
        throw new OperationFlowFailure('infrastructure', 'el asistente de reglas no declara dos pasos');
      }
      const buttons = stepButtons(page, rulesWizard);
      const title = rulesWizard.locator('h3.wizard-step-title');

      // La entrada anterior es el listado del Workspace: el segundo atrás sale
      // de la configuración y no del asistente a otro de sus pasos.
      await openSettled(page, '/workspace');
      await openSettled(page, `${configurationUrl}?step=${firstStep.id}`);
      await expect(title).toHaveText(firstStep.label);
      await expect(buttons.nth(0)).toHaveAttribute('aria-current', 'step');
      await expectStepUrl(page, firstStep.id);

      // Un movimiento del usuario: una entrada y una sola.
      await buttons.nth(1).click();
      await expectStepUrl(page, secondStep.id);
      await expect(title).toHaveText(secondStep.label);
      await expect(buttons.nth(1)).toHaveAttribute('aria-current', 'step');

      await page.goBack();
      await expectStepUrl(page, firstStep.id);
      await expect(title).toHaveText(firstStep.label);
      await expect(buttons.nth(0)).toHaveAttribute('aria-current', 'step');
      await expect(buttons.nth(1)).not.toHaveAttribute('aria-current', 'step');

      await page.goBack();
      await expect(page).toHaveURL(/\/workspace$/);
      await expect(page.locator('section.wizard-shell')).toHaveCount(0);
    });
    record('wizard-back-navigation');
    await openSettled(page, configurationUrl);

    // ------------------------------------------------------------------
    // 5. Inscripción bloqueada por tamaño en el asistente de fases.
    // ------------------------------------------------------------------
    await check('inscripcion-bloqueada', async () => {
      const modeSelect = phasesWizard.getByRole('combobox', {
        name: namePattern(labelText(E2E_LABELS.stageModeField)),
      });
      await modeSelect.selectOption('create');
      await clickStepAndSettle(page, phasesWizard, PHASES_STEPS, 0, 'identidad-de-la-fase');
      await phasesWizard
        .getByRole('textbox', { name: namePattern(labelText(E2E_LABELS.workspaceName)) })
        .fill(BLOCKED_STAGE);
      await phasesWizard
        .getByRole('spinbutton', { name: namePattern(labelText(E2E_LABELS.stageOrderField)) })
        .fill('2');
      const next = phasesWizard.getByRole('button', {
        name: labelText(E2E_LABELS.wizardNext),
        exact: true,
      });
      await next.click();
      await expectStepUrl(page, 'phases.composition');
      const box = phasesWizard.getByRole('checkbox').first();
      await expect(box).toBeVisible();
      await box.check();

      await expect(
        phasesWizard.getByText(labelText(E2E_LABELS.stageEnrollmentBlocked), { exact: true }),
      ).toBeVisible();
      await expect(phasesWizard.getByText(/No se puede inscribir/)).toContainText(
        /hay 0 jugadores activos, el mínimo es 1 y faltan 1/,
      );

      await next.click();
      await expectStepUrl(page, 'phases.review');
      await expect(phasesWizard.locator('h3.wizard-step-title')).toHaveText(
        labelText(E2E_LABELS.phasesStepReview),
      );
      await phasesWizard
        .getByRole('button', { name: labelText(E2E_LABELS.stageConfirmCreate), exact: true })
        .click();
      await expect(
        phasesWizard.getByRole('alert').filter({ hasText: 'Plantilla fuera de rango' }),
      ).toBeVisible({ timeout: MAX_MS.initialConnected });
      await expect(
        phasesWizard.getByRole('alert').filter({ hasText: 'Plantilla fuera de rango' }),
      ).toContainText(/mínimo: 1/);
      await expect(
        phasesWizard
          .getByRole('alert')
          .filter({ hasText: labelText(E2E_LABELS.stagePartial) }),
      ).toBeVisible();
    });
    record('enrollment-blocked');
    record('enrollment-rejected');

    // ------------------------------------------------------------------
    // 6. Operación del torneo nuevo: advertencia y apertura bloqueada.
    // ------------------------------------------------------------------
    await page
      .getByRole('navigation', { name: labelText(E2E_LABELS.tournamentNav), exact: true })
      .getByRole('link', { name: labelText(E2E_LABELS.navCalendar), exact: true })
      .click();
    await expect(
      page.getByRole('heading', { name: labelText(E2E_LABELS.calendarTitle), exact: true }),
    ).toBeVisible({ timeout: MAX_MS.initialConnected });

    await check('partido-creado-y-operacion', async () => {
      const stageSelect = page
        .getByRole('combobox', { name: namePattern(labelText(E2E_LABELS.stageField)) })
        .first();
      await expect(stageSelect.locator('option').filter({ hasText: FLOW_STAGE })).toHaveCount(1, {
        timeout: MAX_MS.initialConnected,
      });
      await selectOptionContaining(stageSelect, FLOW_STAGE);
      await selectOptionContaining(
        page.getByRole('combobox', { name: namePattern(labelText(E2E_LABELS.homeField)) }),
        homeTeam.name,
      );
      await selectOptionContaining(
        page.getByRole('combobox', { name: namePattern(labelText(E2E_LABELS.awayField)) }),
        awayTeam.name,
      );
      await page
        .getByRole('spinbutton', { name: namePattern(labelText(E2E_LABELS.matchdayField)) })
        .fill('1');
      await page
        .getByLabel(namePattern(labelText(E2E_LABELS.matchDateField)))
        .fill(futureMatchDateLocal());
      await page
        .getByRole('button', { name: labelText(E2E_LABELS.createMatch), exact: true })
        .click();
      const link = page
        .getByRole('link', {
          name: new RegExp(
            `${escapeRegExp(homeTeam.name)}.*${escapeRegExp(awayTeam.name)}`,
          ),
        })
        .first();
      await expect(link).toBeVisible({ timeout: MAX_MS.initialConnected });
      await link.click();
      const heading = page.getByRole('heading', { level: 1 });
      await expect(heading).toContainText(homeTeam.name);
      await expect(heading).toContainText(awayTeam.name);
      await expect(page.getByText('Formato 7v7 · alineación sin esquema táctico', { exact: true })).toBeVisible();
    });
    record('operation-format-warning');

    await check('apertura-bloqueada', async () => {
      await page
        .getByRole('button', { name: labelText(E2E_LABELS.startNextSegment), exact: true })
        .click();
      const openingAlert = page
        .getByRole('alert')
        .filter({ hasText: labelText(E2E_LABELS.openingBlockedTitle) });
      await expect(openingAlert).toBeVisible({ timeout: MAX_MS.initialConnected });
      await expect(openingAlert).toContainText(/0 jugadores activos/);
      await expect(openingAlert).toContainText(/mínimo:? 1/);
      await expect(
        page.getByText(formatCount(labelText(E2E_LABELS.matchSegments), 0), { exact: true }),
      ).toBeVisible();
    });
    record('opening-blocked');

    // ------------------------------------------------------------------
    // 6b. Cerrar el acta sin rechazo por minuto (RF-032). El cierre exige la
    //     versión publicada y un jugador de cada equipo: se publica el borrador
    //     del torneo de prueba, se inscribe un jugador por equipo, se abre el
    //     partido y se registra un evento en el límite exacto (89 + 1 = 90).
    // ------------------------------------------------------------------
    const operationUrl = page.url();

    await check('version-publicada', async () => {
      await openSettled(page, `/workspace/tournaments/${encodeURIComponent(flowTournamentId)}`);
      const publish = page.getByRole('button', {
        name: labelText(E2E_LABELS.publishDraft),
        exact: true,
      });
      await expect(publish).toBeVisible({ timeout: MAX_MS.initialConnected });
      page.once('dialog', (dialog) => void dialog.accept());
      await publish.click();
      await expect(publish).toHaveCount(0, { timeout: MAX_MS.initialConnected });
      await expect(
        versionSelect
          .locator('option')
          .filter({ hasText: labelText(E2E_LABELS.statusPublished) }),
      ).toHaveCount(1);
    });
    record('version-published');

    const flowPlayers = [
      {
        team: homeTeam.name,
        first: 'Jugador',
        last: `Local ${runSuffix}`,
        document: `LOC-${runSuffix}`,
        dorsal: '7',
      },
      {
        team: awayTeam.name,
        first: 'Jugador',
        last: `Visitante ${runSuffix}`,
        document: `VIS-${runSuffix}`,
        dorsal: '9',
      },
    ] as const;

    const rostersUrl = `/workspace/tournaments/${encodeURIComponent(flowTournamentId)}/rosters`;
    await openSettled(page, rostersUrl);

    // Los identificadores salen de las opciones del selector de equipo. La
    // pantalla se abre con `?team=` para no depender de la selección por
    // defecto: la dirección fija el equipo desde el primer render.
    const teamIdByName = await page
      .getByRole('combobox', { name: namePattern(labelText(E2E_LABELS.rosterTeamField)) })
      .first()
      .locator('option')
      .evaluateAll((options) => Object.fromEntries(
        (options as HTMLOptionElement[])
          .map((option) => [option.textContent ?? '', option.value] as const)
          .filter(([text]) => text.length > 0),
      ));

    const homeTeamId = teamIdByName[homeTeam.name];
    if (!homeTeamId) {
      throw new OperationFlowFailure('infrastructure', `sin identificador para ${homeTeam.name}`);
    }
    const rostersTeamUrl = (teamId: string): string =>
      `${rostersUrl}?team=${encodeURIComponent(teamId)}`;
    const lockNotice = page.getByText(
      fillLabel(labelText(E2E_LABELS.rosterLockNotice), { matchday: LOCK_MATCHDAY }),
      { exact: true },
    );

    // Equivalencia del aviso de cierre (RF-039, criterio 13), lado 1: con la
    // jornada todavía sin confirmar la pantalla no avisa y el alta responde 201.
    await check('aviso-de-cierre-ausente', async () => {
      await openSettled(page, rostersTeamUrl(homeTeamId));
      await expect(
        page.getByRole('heading', { name: labelText(E2E_LABELS.rostersTitle), exact: true }),
      ).toBeVisible({ timeout: MAX_MS.initialConnected });
      await expect(lockNotice).toHaveCount(0);
    });
    record('roster-lock-absent');

    for (const player of flowPlayers) {
      await check(`jugador-inscrito-${player.dorsal}`, async () => {
        const teamId = teamIdByName[player.team];
        if (!teamId) {
          throw new OperationFlowFailure('infrastructure', `sin identificador para ${player.team}`);
        }

        await openSettled(page, rostersTeamUrl(teamId));

        await expect(
          page.getByRole('heading', {
            name: labelText(E2E_LABELS.rostersTitle),
            exact: true,
          }),
        ).toBeVisible({ timeout: MAX_MS.initialConnected });
        await expect(
          page.getByRole('heading', {
            level: 2,
            name: new RegExp(
              `^${escapeRegExp(labelText(E2E_LABELS.rosterListTitle).replace('{team}', player.team))}$`,
            ),
          }),
        ).toBeVisible({ timeout: MAX_MS.initialConnected });

        const firstName = page.getByRole('textbox', {
          name: namePattern(labelText(E2E_LABELS.playerFirstName)),
        });
        const lastName = page.getByRole('textbox', {
          name: namePattern(labelText(E2E_LABELS.playerLastName)),
        });
        const document = page.getByRole('textbox', {
          name: namePattern(labelText(E2E_LABELS.playerDocument)),
        });
        const birthDate = page.getByLabel(namePattern(labelText(E2E_LABELS.playerBirthDate)));
        const dorsal = page.getByRole('spinbutton', {
          name: namePattern(labelText(E2E_LABELS.playerNumber)),
        });
        await firstName.fill(player.first);
        await lastName.fill(player.last);
        await document.fill(player.document);
        await birthDate.fill('2000-01-01');
        await dorsal.fill(player.dorsal);

        // El alta exige el formulario completo: se comprueba antes de enviar
        // para que un valor perdido falle aquí y no como un rechazo del alta.
        await expect(firstName).toHaveValue(player.first);
        await expect(lastName).toHaveValue(player.last);
        await expect(document).toHaveValue(player.document);
        await expect(birthDate).toHaveValue('2000-01-01');
        await expect(dorsal).toHaveValue(player.dorsal);

        const addButton = page.getByRole('button', {
          name: labelText(E2E_LABELS.addPlayer),
          exact: true,
        });
        const [created] = await Promise.all([
          page.waitForResponse(
            (candidate) =>
              candidate.url().includes('/rosters') && candidate.request().method() === 'POST',
          ),
          addButton.click(),
        ]);
        if (created.status() !== 201) {
          throw new OperationFlowFailure(
            'behavioral',
            `el alta sin aviso de cierre respondió ${created.status()} y se esperaba 201`,
          );
        }

        await expect(
          page.getByText(`#${player.dorsal} · ${player.first} ${player.last}`, { exact: true }),
        ).toBeVisible({ timeout: MAX_MS.initialConnected });
      });
    }
    record('roster-players-added');
    record('roster-created-without-lock');

    await openSettled(page, operationUrl);

    await check('apertura-del-partido', async () => {
      await page
        .getByRole('button', { name: labelText(E2E_LABELS.startNextSegment), exact: true })
        .click();
      await expect(
        page.getByText(formatCount(labelText(E2E_LABELS.matchSegments), 1), { exact: true }),
      ).toBeVisible({ timeout: MAX_MS.initialConnected });
    });
    record('segment-opened');

    // RF-032: **un segmento en el límite**. El segmento vigente termina en el
    // minuto 90 y el nuevo empieza en 90: los dos quedan dentro del máximo de la
    // resolución prevista y el cierre no los rechaza. Se crea antes de la
    // planilla para que el cierre valide la planilla del segmento vigente.
    await check('segmento-en-el-limite', async () => {
      const startMinute = page.getByRole('spinbutton', {
        name: namePattern(labelText(E2E_LABELS.segmentStartField)),
      });
      await startMinute.fill('90');
      await expect(startMinute).toHaveValue('90');
      await page
        .getByRole('button', { name: labelText(E2E_LABELS.createSegment), exact: true })
        .click();
      await expect(
        page.getByText(formatCount(labelText(E2E_LABELS.matchSegments), 2), { exact: true }),
      ).toBeVisible({ timeout: MAX_MS.initialConnected });
      await expect(page.getByRole('alert').filter({ hasText: 'excede el máximo' })).toHaveCount(0);
    });
    record('segment-at-limit');

    await check('planilla-guardada', async () => {
      for (const player of flowPlayers) {
        await page
          .getByRole('combobox', {
            name: `${labelText(E2E_LABELS.lineupRole)} ${player.first} ${player.last}`,
            exact: true,
          })
          .selectOption('starter');
      }
      const saveLineup = page.getByRole('button', {
        name: labelText(E2E_LABELS.saveLineup),
        exact: true,
      });
      const [response] = await Promise.all([
        page.waitForResponse(
          (candidate) =>
            candidate.url().includes('/lineup') && candidate.request().method() === 'PUT',
        ),
        saveLineup.click(),
      ]);
      if (!response.ok()) {
        throw new Error(`la planilla respondió ${response.status()}`);
      }
      // La respuesta llega antes que el refresco de la operación: se espera a
      // que la planilla guardada ya ofrezca al jugador en el alta de eventos.
      await expect(
        page
          .getByRole('combobox', { name: namePattern(labelText(E2E_LABELS.eventPlayerField)) })
          .first()
          .locator('option')
          .filter({ hasText: flowPlayers[0].last }),
      ).toHaveCount(1, { timeout: MAX_MS.initialConnected });
      // El refresco reconstruye la planilla local desde las formaciones (que
      // este escenario no configura); se vuelve a marcar un titular por equipo
      // para que el cierre encuentre la planilla completa que el servidor ya
      // tiene guardada.
      for (const player of flowPlayers) {
        await page
          .getByRole('combobox', {
            name: `${labelText(E2E_LABELS.lineupRole)} ${player.first} ${player.last}`,
            exact: true,
          })
          .selectOption('starter');
      }
    });
    record('lineup-saved');

    await check('evento-en-el-limite', async () => {
      const eventsPanel = reportPanel(page);
      const eventType = eventsPanel.getByRole('combobox', {
        name: namePattern(labelText(E2E_LABELS.operationEventType)),
      });
      await eventType.selectOption('yellow_card');
      await selectOptionContaining(
        eventsPanel
          .getByRole('combobox', { name: namePattern(labelText(E2E_LABELS.eventTeamField)) })
          .first(),
        flowPlayers[0].team,
      );
      await selectOptionContaining(
        eventsPanel
          .getByRole('combobox', { name: namePattern(labelText(E2E_LABELS.eventPlayerField)) })
          .first(),
        flowPlayers[0].last,
      );
      await eventsPanel
        .getByRole('spinbutton', { name: namePattern(labelText(E2E_LABELS.operationEventMinute)) })
        .fill('90');
      await eventsPanel
        .getByRole('spinbutton', { name: namePattern(labelText(E2E_LABELS.eventAddedMinuteField)) })
        .fill('1');
      await eventsPanel
        .getByRole('button', { name: labelText(E2E_LABELS.eventAdd), exact: true })
        .click();
      await expect(eventsPanel.getByText(/^90'\s·\s/).first()).toBeVisible();
      await expect(
        page.getByRole('alert').filter({ hasText: 'supera el máximo' }),
      ).toHaveCount(0);
    });
    record('event-at-limit');

    // RF-032/RNF-005: los dos avisos del límite se anuncian (`role="alert"`
    // visible), nombran el máximo aplicable y no escriben nada. No se comprueba
    // un movimiento de foco porque el aviso no es enfocable y el control que lo
    // provoca queda deshabilitado durante la petición; el anuncio es lo que el
    // producto garantiza.
    await check('aviso-de-evento-por-encima-del-limite', async () => {
      const eventsPanel = reportPanel(page);
      const minute = eventsPanel.getByRole('spinbutton', {
        name: namePattern(labelText(E2E_LABELS.operationEventMinute)),
      });
      // Antes del minuto final la suma no puede pasar el máximo: 89 + 2 > 90.
      await minute.fill('89');
      await eventsPanel
        .getByRole('spinbutton', { name: namePattern(labelText(E2E_LABELS.eventAddedMinuteField)) })
        .fill('2');
      await eventsPanel
        .getByRole('button', { name: labelText(E2E_LABELS.eventAdd), exact: true })
        .click();
      const alert = page.getByRole('alert').filter({ hasText: 'supera el máximo de 90' });
      await expect(alert).toBeVisible();
      await expect(alert).toHaveAttribute('role', 'alert');
      // El evento no se añade: sigue habiendo un único evento en el borrador.
      await expect(eventsPanel.getByText(/^90'\s·\s/)).toHaveCount(1);
    });
    record('event-limit-announced');

    await check('aviso-de-segmento-por-encima-del-limite', async () => {
      const startMinute = page.getByRole('spinbutton', {
        name: namePattern(labelText(E2E_LABELS.segmentStartField)),
      });
      await startMinute.fill('91');
      await expect(startMinute).toHaveValue('91');
      await page
        .getByRole('button', { name: labelText(E2E_LABELS.createSegment), exact: true })
        .click();
      const alert = page.getByRole('alert').filter({ hasText: 'excede el máximo' });
      await expect(alert).toBeVisible({ timeout: MAX_MS.initialConnected });
      await expect(alert).toContainText('90');
      // El segmento no se crea: siguen siendo dos.
      await expect(
        page.getByText(formatCount(labelText(E2E_LABELS.matchSegments), 2), { exact: true }),
      ).toBeVisible();
      await expect(
        page.getByText(formatCount(labelText(E2E_LABELS.matchSegments), 3), { exact: true }),
      ).toHaveCount(0);
    });
    record('segment-limit-announced');

    await check('cierre-sin-rechazo-por-minuto', async () => {
      const close = page.getByRole('button', {
        name: labelText(E2E_LABELS.closeReport),
        exact: true,
      });
      page.once('dialog', (dialog) => void dialog.accept());
      await close.click();
      await expect(
        page.getByRole('button', { name: labelText(E2E_LABELS.reportClosed), exact: true }),
      ).toBeVisible({ timeout: MAX_MS.initialConnected });
      await expect(
        page.getByRole('alert').filter({ hasText: 'supera el máximo' }),
      ).toHaveCount(0);
    });
    record('report-closed');

    // ------------------------------------------------------------------
    // 9. Equivalencia del aviso de cierre (RF-039, criterio 13), lado 2: con
    //    la misma versión publicada, la jornada 1 de la primera fase ya está
    //    confirmada, así que la pantalla avisa y el alta responde el 409 de
    //    cierre (no el de tamaño) sin escribir la fila. Se verifica en el
    //    navegador y no con una prueba de integración porque lo que debe
    //    equivaler es el cálculo de la pantalla y la respuesta real del
    //    servidor sobre el mismo torneo y la misma versión.
    // ------------------------------------------------------------------
    await check('aviso-de-cierre-visible', async () => {
      await openSettled(page, rostersTeamUrl(homeTeamId));
      await expect(lockNotice).toBeVisible({ timeout: MAX_MS.initialConnected });
    });
    record('roster-lock-visible');

    await check('alta-bloqueada-por-el-cierre', async () => {
      const locked = {
        first: 'Jugador',
        last: `Bloqueado ${runSuffix}`,
        document: `LOCK-${runSuffix}`,
        dorsal: '11',
      };
      await page
        .getByRole('textbox', { name: namePattern(labelText(E2E_LABELS.playerFirstName)) })
        .fill(locked.first);
      await page
        .getByRole('textbox', { name: namePattern(labelText(E2E_LABELS.playerLastName)) })
        .fill(locked.last);
      await page
        .getByRole('textbox', { name: namePattern(labelText(E2E_LABELS.playerDocument)) })
        .fill(locked.document);
      await page
        .getByLabel(namePattern(labelText(E2E_LABELS.playerBirthDate)))
        .fill('2000-01-01');
      await page
        .getByRole('spinbutton', { name: namePattern(labelText(E2E_LABELS.playerNumber)) })
        .fill(locked.dorsal);

      const [rejected] = await Promise.all([
        page.waitForResponse(
          (candidate) =>
            candidate.url().includes('/rosters') && candidate.request().method() === 'POST',
        ),
        page
          .getByRole('button', { name: labelText(E2E_LABELS.addPlayer), exact: true })
          .click(),
      ]);
      if (rejected.status() !== 409) {
        throw new OperationFlowFailure(
          'behavioral',
          `el alta con el aviso de cierre respondió ${rejected.status()} y se esperaba 409`,
        );
      }
      const body = (await rejected.json()) as { detail?: unknown; code?: unknown };
      if (
        typeof body.detail !== 'string'
        || !body.detail.includes(ROSTER_LOCK_SERVER_DETAIL)
      ) {
        throw new OperationFlowFailure(
          'behavioral',
          `el 409 del cierre no trae el mensaje de cierre: ${JSON.stringify(body)}`,
        );
      }
      if (body.code === 'ROSTER_SIZE_OUT_OF_RANGE') {
        throw new OperationFlowFailure(
          'behavioral',
          'el 409 del cierre no puede ser el de tamaño de plantilla',
        );
      }
      await expect(
        page.getByRole('alert').filter({ hasText: ROSTER_LOCK_SERVER_DETAIL }),
      ).toBeVisible();
      await expect(
        page.getByText(`#${locked.dorsal} · ${locked.first} ${locked.last}`, { exact: true }),
      ).toHaveCount(0);
    });
    record('roster-create-locked');

  } catch (error) {
    failure =
      error instanceof OperationFlowFailure
        ? error
        : new OperationFlowFailure('infrastructure', `scenario-error: ${describeError(error)}`);
  } finally {
    page.off('console', onConsole);
    page.off('pageerror', onPageError);
  }

  const result = await finalize(failure ? failure.verdict : 'passed', failure?.cause ?? null);
  if (failure) throw failure;
  return result;
}

/** Ruta del artefacto del escenario (comprobable por el runner y por el spec). */
export function operationFlowArtifactPath(): string {
  return reportPath(`view-${OPERATION_FLOW_VIEW}.json`);
}
