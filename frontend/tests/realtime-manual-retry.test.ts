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

const NAMESPACES: RealtimeLabelNamespace[] = ['public', 'workspace', 'match'];

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
