import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  isReconnection,
  needsNewSocketSession,
  type RealtimeConnectionStatus,
} from '../app/utils/realtimeConnection.ts';
import { shouldPollPublicRealtime } from '../app/utils/realtimeReload.ts';
import { shouldForceReconnect } from '../app/utils/realtimeRetry.ts';
import {
  realtimeStatusLabelKey,
  type RealtimeLabelNamespace,
} from '../app/utils/realtimeStatusLabel.ts';

const translations = readFileSync(
  new URL('../app/composables/useI18n.ts', import.meta.url),
  'utf8',
);
const realtimeComposable = readFileSync(
  new URL('../app/composables/useRealtime.ts', import.meta.url),
  'utf8',
);

const NAMESPACES: RealtimeLabelNamespace[] = ['public', 'workspace', 'match'];

/**
 * Las tres vistas donde existe el control «Reintentar» (RF-003). Cada una debe
 * calcular su etiqueta con la función compartida y anunciar el estado manual.
 */
function loadViews(): Array<{ file: string; namespace: RealtimeLabelNamespace; source: string }> {
  const views = [
    { file: '../app/pages/tournaments/[id].vue', namespace: 'public' as const },
    { file: '../app/pages/workspace/index.vue', namespace: 'workspace' as const },
    { file: '../app/pages/workspace/matches/[id].vue', namespace: 'match' as const },
  ];
  return views.map(({ file, namespace }) => ({
    file,
    namespace,
    source: readFileSync(new URL(file, import.meta.url), 'utf8'),
  }));
}

const VIEWS = loadViews();

function catalogSlices(): { spanish: string; english: string } {
  const englishStart = translations.indexOf('\n  en: {');
  assert.ok(englishStart > 0, 'the English catalog is missing');
  return {
    spanish: translations.slice(0, englishStart),
    english: translations.slice(englishStart),
  };
}

function messageText(catalog: string, key: string): string {
  const escaped = key.replace(/\./g, '\\.');
  const match = catalog.match(new RegExp(`'${escaped}':\\s*'([^']*)'`));
  if (!match) assert.fail(`missing key ${key}`);
  return match[1] ?? '';
}

/**
 * Modelo puro de la decisión de `retry()`: la pulsación solo inicia un intento
 * nuevo si el estado exige derribar la conexión o si el guard de sesión admite
 * un socket lógico nuevo. Con el estado manual y un socket vivo no hay intento.
 */
function startsNewAttempt(input: {
  status: RealtimeConnectionStatus;
  hasSocket: boolean;
  scopeKey: string;
  sessionVersion: number;
}): boolean {
  const force = shouldForceReconnect(input.status, input.hasSocket);
  return needsNewSocketSession({
    hasSocket: force ? false : input.hasSocket,
    previousScopeKey: input.scopeKey,
    nextScopeKey: input.scopeKey,
    publicScope: input.scopeKey.startsWith('public:'),
    previousSessionVersion: input.sessionVersion,
    sessionVersion: input.sessionVersion,
  });
}

test('el reintento manual es un estado de conexión propio', () => {
  // `retrying` es parte del union: no existe un booleano paralelo al estado.
  const statuses: RealtimeConnectionStatus[] = [
    'idle',
    'connecting',
    'connected',
    'reconnecting',
    'retrying',
    'error',
  ];
  const retrying: RealtimeConnectionStatus = 'retrying';

  assert.equal(statuses.includes(retrying), true);
});

test('cada vista nombra el reintento manual con su propia clave', () => {
  for (const namespace of NAMESPACES) {
    assert.equal(
      realtimeStatusLabelKey('retrying', namespace),
      `${namespace}.realtimeRetrying`,
      namespace,
    );
  }
});

test('el reintento manual no se confunde con la reconexión ni con otro estado', () => {
  for (const namespace of NAMESPACES) {
    const retrying = realtimeStatusLabelKey('retrying', namespace);
    const reconnecting = realtimeStatusLabelKey('reconnecting', namespace);
    const connected = realtimeStatusLabelKey('connected', namespace);
    const error = realtimeStatusLabelKey('error', namespace);

    assert.equal(typeof retrying, 'string', namespace);
    // Comparación exacta, no por subcadena: la etiqueta del manual es otra.
    assert.notEqual(retrying, reconnecting);
    assert.notEqual(retrying, connected);
    assert.notEqual(retrying, error);
    assert.equal(reconnecting, `${namespace}.realtimeReconnecting`);
    assert.equal(connected, `${namespace}.realtimeConnected`);
    assert.equal(error, `${namespace}.realtimeError`);
  }
});

test('sin nada que anunciar la vista no recibe etiqueta', () => {
  for (const namespace of NAMESPACES) {
    assert.equal(realtimeStatusLabelKey('idle', namespace), null, namespace);
    assert.equal(realtimeStatusLabelKey('connecting', namespace), null, namespace);
  }
});

test('las tres claves de reintento existen y no están vacías en es y en', () => {
  const { spanish, english } = catalogSlices();

  for (const namespace of NAMESPACES) {
    const key = `${namespace}.realtimeRetrying`;
    const es = messageText(spanish, key);
    const en = messageText(english, key);

    assert.ok(es.trim().length > 0, `empty Spanish text for ${key}`);
    assert.ok(en.trim().length > 0, `empty English text for ${key}`);
  }
});

test('el texto del manual es propio y distinto del automático en ambos idiomas', () => {
  const { spanish, english } = catalogSlices();

  for (const namespace of NAMESPACES) {
    const retrying = `${namespace}.realtimeRetrying`;
    const reconnecting = `${namespace}.realtimeReconnecting`;
    const connected = `${namespace}.realtimeConnected`;
    const error = `${namespace}.realtimeError`;

    const esRetrying = messageText(spanish, retrying);
    const esReconnecting = messageText(spanish, reconnecting);
    const enRetrying = messageText(english, retrying);
    const enReconnecting = messageText(english, reconnecting);

    assert.notEqual(esRetrying, esReconnecting, `Spanish manual text equals the automatic one: ${namespace}`);
    assert.notEqual(enRetrying, enReconnecting, `English manual text equals the automatic one: ${namespace}`);
    assert.notEqual(esRetrying, messageText(spanish, connected), namespace);
    assert.notEqual(esRetrying, messageText(spanish, error), namespace);
    assert.notEqual(enRetrying, messageText(english, connected), namespace);
    assert.notEqual(enRetrying, messageText(english, error), namespace);
    // El texto existe en los dos idiomas y no es el mismo en ambos.
    assert.notEqual(esRetrying, enRetrying, namespace);
  }
});

test('con el intento manual en curso y el socket vivo no se inicia otro', () => {
  const manual = {
    status: 'retrying' as RealtimeConnectionStatus,
    hasSocket: true,
    scopeKey: 'public:tournament-1',
    sessionVersion: 0,
  };

  // La segunda pulsación no derriba el socket del intento en curso…
  assert.equal(shouldForceReconnect(manual.status, manual.hasSocket), false);
  // …y el guard de sesión tampoco admite un socket lógico nuevo: no-op.
  assert.equal(startsNewAttempt(manual), false);
});

test('sin socket el estado manual admite un intento nuevo', () => {
  assert.equal(shouldForceReconnect('retrying', false), true);
  assert.equal(
    startsNewAttempt({
      status: 'retrying',
      hasSocket: false,
      scopeKey: 'organization:org-a',
      sessionVersion: 2,
    }),
    true,
  );
});

test('un estado de error sí inicia un intento nuevo y vacía el socket zombi', () => {
  assert.equal(
    startsNewAttempt({
      status: 'error',
      hasSocket: true,
      scopeKey: 'organization:org-a',
      sessionVersion: 2,
    }),
    true,
  );
});

test('la pulsación que abre un intento nuevo no se contabiliza como reconexión', () => {
  // El estado manual no es una pérdida observada: el respaldo de recarga de la
  // reconexión no se arma con la pulsación.
  assert.equal(
    isReconnection({
      hasConnectedOnce: true,
      previousStatus: 'retrying',
      nextStatus: 'connected',
    }),
    false,
  );
});

test('la página pública sigue refrescándose por HTTP mientras dura el manual', () => {
  assert.equal(shouldPollPublicRealtime('retrying'), true);
});

/** Cuerpo de una función del composable, contando llaves y sin cortar en plantillas. */
function functionBody(source: string, signature: string): string {
  const start = source.indexOf(signature);
  assert.ok(start >= 0, `missing ${signature}`);
  const open = source.indexOf('{', start);
  assert.ok(open > start, `${signature} needs a body`);
  let depth = 0;
  for (let index = open; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1;
    if (source[index] === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(open + 1, index);
    }
  }
  assert.fail(`unbalanced body for ${signature}`);
}

/** Trozo del `<span>` que anuncia la etiqueta, desde su apertura hasta el texto. */
function statusElement(source: string): string {
  const marker = '{{ realtimeStatusLabel }}';
  const label = source.indexOf(marker);
  assert.ok(label >= 0, 'the view must render realtimeStatusLabel');
  let open = source.lastIndexOf('<span', label);
  while (open >= 0) {
    const element = source.slice(open, label + marker.length);
    if (/role="status"/.test(element)) return element;
    open = source.lastIndexOf('<span', open - 1);
  }
  assert.fail('the label must live inside a role="status" element');
}

test('el catálogo cubre toda etiqueta visible de las tres vistas en es y en', () => {
  const { spanish, english } = catalogSlices();
  const visible: RealtimeConnectionStatus[] = ['connected', 'reconnecting', 'retrying', 'error'];

  for (const namespace of NAMESPACES) {
    for (const status of visible) {
      const key = realtimeStatusLabelKey(status, namespace);
      assert.ok(key, `${namespace}/${status} must have a label key`);
      const escaped = key.replace(/\./g, '\\.');
      assert.match(spanish, new RegExp(`'${escaped}':`), `missing Spanish key ${key}`);
      assert.match(english, new RegExp(`'${escaped}':`), `missing English key ${key}`);
      assert.ok(messageText(spanish, key).trim().length > 0, `empty Spanish text for ${key}`);
      assert.ok(messageText(english, key).trim().length > 0, `empty English text for ${key}`);
    }
  }

  // Paridad: tres claves de reintento manual en cada catálogo, ni una más.
  assert.equal(spanish.match(/\.realtimeRetrying':/g)?.length ?? 0, 3);
  assert.equal(english.match(/\.realtimeRetrying':/g)?.length ?? 0, 3);
  assert.equal(spanish.match(/\.realtimeReconnecting':/g)?.length ?? 0, 3);
  assert.equal(english.match(/\.realtimeReconnecting':/g)?.length ?? 0, 3);
});

test('connect() devuelve si inició el intento y no fija el estado manual', () => {
  const signature = 'function connect(input?: HandlerInput, options?: ConnectionOptions): boolean';
  assert.ok(realtimeComposable.includes(signature), 'connect() must report whether it created a socket');

  const body = functionBody(realtimeComposable, signature);
  const guard = body.indexOf('needsNewSocketSession(');
  const noAttempt = body.indexOf('return false;', guard);
  const socketCreation = body.indexOf('socket = io(');
  const started = body.lastIndexOf('return true;');

  assert.ok(guard >= 0, 'connect() must keep the session-reuse guard');
  assert.ok(noAttempt > guard, 'the guard must return false without starting an attempt');
  assert.ok(socketCreation > noAttempt, 'the socket must be created only after the guard admits it');
  assert.ok(started > socketCreation, 'connect() must return true only after creating the socket');
  assert.doesNotMatch(body, /setStatus\('retrying'\)/, 'connect() must never set the manual state');
});

test('retry() fija el estado manual solo cuando el intento se inició de verdad', () => {
  const signature = 'function retry(): boolean';
  assert.ok(realtimeComposable.includes(signature), 'retry() must report whether it showed the manual state');

  const body = functionBody(realtimeComposable, signature);
  const attempt = body.indexOf('const started = connect(activeHandlers)');
  const noAttempt = body.indexOf('return false;', attempt);
  const manual = body.indexOf("setStatus('retrying')");

  assert.ok(attempt >= 0, 'retry() must ask connect() for the attempt');
  assert.ok(noAttempt > attempt, 'a click that creates no socket must return false');
  assert.match(body, /if \(!started\) return false;/, 'the no-op must be explicit');
  assert.ok(manual > noAttempt, "retrying is set only after connect() created the socket");

  // Una única asignación en todo el composable, y siempre dentro de retry().
  assert.equal(realtimeComposable.match(/setStatus\('retrying'\)/g)?.length, 1);
  assert.ok(
    realtimeComposable.indexOf("setStatus('retrying')") > realtimeComposable.indexOf('function retry()'),
    'no transition may set the manual state outside retry()',
  );
});

test('un retry() sin socket nuevo no deja la vista en reintento', () => {
  // El guard de sesión convierte la segunda pulsación en un no-op…
  assert.equal(
    startsNewAttempt({
      status: 'retrying',
      hasSocket: true,
      scopeKey: 'public:tournament-1',
      sessionVersion: 0,
    }),
    false,
  );
  // …y el composable devuelve false antes de fijar el estado manual. La fuente
  // lo demuestra en orden: connect() → guard `!started` → setStatus('retrying').
  const body = functionBody(realtimeComposable, 'function retry(): boolean');
  const noAttempt = body.indexOf('if (!started) return false;');
  assert.ok(noAttempt >= 0);
  assert.ok(noAttempt < body.indexOf("setStatus('retrying')"));
});

test('las tres vistas calculan la etiqueta con la función compartida', () => {
  for (const view of VIEWS) {
    assert.match(
      view.source,
      /import \{ realtimeStatusLabelKey \} from '~\/utils\/realtimeStatusLabel';/,
      view.file,
    );
    assert.match(
      view.source,
      new RegExp(`realtimeStatusLabelKey\\(realtime\\.status\\.value, '${view.namespace}'\\)`),
      `${view.file} must use its own namespace`,
    );
    // Sin cascadas duplicadas ni claves escritas a mano en la vista.
    assert.doesNotMatch(
      view.source,
      /'(public|workspace|match)\.realtime(Connected|Reconnecting|Retrying|Error)'/,
      `${view.file} must not duplicate the label cascade`,
    );
    assert.doesNotMatch(view.source, /Reintentando|Retrying/, view.file);
  }
});

test('las tres vistas anuncian el estado manual en un role="status"', () => {
  for (const view of VIEWS) {
    const element = statusElement(view.source);
    assert.match(element, /role="status"/, `${view.file} must announce the state`);
    assert.match(element, /\{\{\s*realtimeStatusLabel\s*\}\}/, view.file);
    // El control sigue existiendo solo en error y desaparece mientras se reintenta.
    assert.match(
      view.source,
      /v-if="realtime\.status\.value === 'error'"/,
      `${view.file} must keep the retry control limited to the error state`,
    );
    assert.match(view.source, /realtime\.retry\(\)/, view.file);
    // El color de aviso se comparte por clase, sin depender solo del color.
    assert.match(view.source, /\.realtime-retrying/, `${view.file} needs the retrying style`);
  }
});

test('el panel del Workspace conserva su fallback cuando no hay nada que anunciar', () => {
  const workspace = VIEWS.find((view) => view.namespace === 'workspace');
  assert.ok(workspace);
  assert.match(workspace.source, /t\('workspace\.activeOperation'\)/);
  // Las vistas que no pintan etiqueta en `connecting` siguen sin pintarla: el
  // `v-if` depende de la etiqueta, no del estado.
  for (const view of VIEWS) {
    if (view.namespace === 'workspace') continue;
    assert.match(view.source, /v-if="realtimeStatusLabel"/, view.file);
  }
});

test('el estado manual no añade lógica de recarga ni de suscripción', () => {
  const body = functionBody(realtimeComposable, 'function retry(): boolean');
  for (const token of ['initialization', 'reconnectJoin', 'reload', 'shouldPollPublicRealtime', 'dedupe']) {
    assert.doesNotMatch(body, new RegExp(token), `retry() must not touch ${token}`);
  }

  // Las decisiones que gobiernan las recargas y la doble pulsación no cambian.
  assert.equal(
    isReconnection({ hasConnectedOnce: true, previousStatus: 'retrying', nextStatus: 'connected' }),
    false,
  );
  assert.equal(shouldPollPublicRealtime('retrying'), true);
  assert.equal(shouldForceReconnect('retrying', true), false);
});
