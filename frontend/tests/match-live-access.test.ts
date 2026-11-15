import assert from 'node:assert/strict';
import test from 'node:test';

import {
  deriveLiveView,
} from '../app/utils/matchLiveAccess.ts';
import {
  normalizeLiveCapabilities,
  type LiveCapabilities,
} from '../app/utils/matchLiveContext.ts';

function caps(overrides: Partial<LiveCapabilities> = {}): LiveCapabilities {
  return {
    can_view: false,
    can_operate: false,
    can_close: false,
    available: true,
    ...overrides,
  };
}

test('VIEW sin OPERATE presenta lector: detalle sin controles ni cierre', () => {
  const view = deriveLiveView(caps({ can_view: true }));
  assert.equal(view.mode, 'reader');
  assert.equal(view.detailVisible, true);
  assert.equal(view.controlsEnabled, false);
  assert.equal(view.closeEnabled, false);
});

test('OPERATE sin VIEW no revela el detalle: escribir no concede leer', () => {
  const view = deriveLiveView(caps({ can_operate: true }));
  assert.equal(view.detailVisible, false);
  // Sin lectura del borrador los controles no se ofrecen (nada que referenciar).
  assert.equal(view.controlsEnabled, false);
  assert.equal(view.closeEnabled, false);
});

test('el observador (ninguna capacidad) queda oculto completo', () => {
  const view = deriveLiveView(caps());
  assert.equal(view.mode, 'hidden');
  assert.equal(view.detailVisible, false);
  assert.equal(view.controlsEnabled, false);
  assert.equal(view.closeEnabled, false);
});

test('el cierre solo existe con can_close propio, nunca por herencia de OPERATE', () => {
  assert.equal(deriveLiveView(caps({ can_view: true, can_operate: true })).closeEnabled, false);
  const view = deriveLiveView(caps({ can_view: true, can_close: true }));
  assert.equal(view.closeEnabled, true);
  assert.equal(view.controlsEnabled, false);
});

test('multirol: las tres capacidades se componen de forma independiente', () => {
  const view = deriveLiveView(caps({ can_view: true, can_operate: true, can_close: true }));
  assert.equal(view.mode, 'operator');
  assert.equal(view.detailVisible, true);
  assert.equal(view.controlsEnabled, true);
  assert.equal(view.closeEnabled, true);
});

test('capacidad retirada (null) limpia la vista privada por completo', () => {
  const view = deriveLiveView(null);
  assert.equal(view.mode, 'hidden');
  assert.equal(view.detailVisible, false);
  assert.equal(view.controlsEnabled, false);
  assert.equal(view.closeEnabled, false);
});

test('respuesta inválida o no disponible equivale a vista oculta', () => {
  assert.equal(deriveLiveView(normalizeLiveCapabilities({ garbage: true })).mode, 'hidden');
  assert.equal(deriveLiveView(caps({ can_view: true, available: false })).mode, 'hidden');
  assert.equal(deriveLiveView(caps({ can_view: true, available: false })).detailVisible, false);
});

test('un lector con can_close sin can_view no ve detalle pero conserva su cierre', () => {
  const view = deriveLiveView(caps({ can_close: true }));
  assert.equal(view.detailVisible, false);
  assert.equal(view.closeEnabled, true);
  assert.equal(view.mode, 'closer');
});
