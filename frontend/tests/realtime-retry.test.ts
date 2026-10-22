import assert from 'node:assert/strict';
import test from 'node:test';

import { needsNewSocketSession } from '../app/utils/realtimeConnection.ts';
import { shouldForceReconnect } from '../app/utils/realtimeRetry.ts';

test('un estado de error fuerza el reintento aunque quede un socket zombi', () => {
  // El socket existe pero no está conectado: hay que destruirlo antes de abrir
  // uno nuevo, o la conexión volvería a terminar sin efecto.
  assert.equal(shouldForceReconnect('error', true), true);
});

test('un estado de error sin socket también fuerza un intento nuevo', () => {
  assert.equal(shouldForceReconnect('error', false), true);
});

test('un socket desconectado fuerza el reintento aunque el objeto siga vivo', () => {
  // Estado a nivel de socket: no hay conexión utilizable.
  assert.equal(shouldForceReconnect('disconnected', true), true);
  assert.equal(shouldForceReconnect('disconnected', false), true);
});

test('una conexión sana no se derriba al reintentar', () => {
  assert.equal(shouldForceReconnect('connected', true), false);
  assert.equal(shouldForceReconnect('connected', false), false);
});

test('un intento en curso con socket no se reinicia ni acumula intentos', () => {
  // Socket.IO ya reintenta solo: pulsar otra vez no debe destruir el socket
  // recién creado (RF-001: no acumular intentos).
  assert.equal(shouldForceReconnect('connecting', true), false);
  assert.equal(shouldForceReconnect('reconnecting', true), false);
});

test('un reintento manual en curso con socket vivo no inicia otro intento', () => {
  // `retrying` es el estado visible del intento que abrió la pulsación: una
  // segunda pulsación no puede derribar ese socket ni acumular un intento
  // (caso límite 3, decisión 7 del plan).
  assert.equal(shouldForceReconnect('retrying', true), false);

  // Sin socket no hay intento que conservar: la pulsación puede reintentar.
  assert.equal(shouldForceReconnect('retrying', false), true);

  // El guard de sesión convierte la doble pulsación en un no-op con socket,
  // mismo alcance y misma versión de sesión.
  assert.equal(
    needsNewSocketSession({
      hasSocket: true,
      previousScopeKey: 'public:tournament-1',
      nextScopeKey: 'public:tournament-1',
      publicScope: true,
      previousSessionVersion: 0,
      sessionVersion: 0,
    }),
    false,
  );
});

test('sin socket, cualquier estado no conectado admite un intento nuevo', () => {
  assert.equal(shouldForceReconnect('idle', false), true);
  assert.equal(shouldForceReconnect('connecting', false), true);
  assert.equal(shouldForceReconnect('reconnecting', false), true);
});

test('el reintento forzado exige una sesión de socket nueva', () => {
  const force = shouldForceReconnect('error', true);
  assert.equal(force, true);

  // retry() destruye el socket cuando la decisión es forzar; con hasSocket en
  // false, needsNewSocketSession no puede devolver temprano (hoy el guard es
  // el que convertía el reintento en un no-op).
  assert.equal(
    needsNewSocketSession({
      hasSocket: force ? false : true,
      previousScopeKey: 'public:tournament-1',
      nextScopeKey: 'public:tournament-1',
      publicScope: true,
      previousSessionVersion: 0,
      sessionVersion: 0,
    }),
    true,
  );
});
