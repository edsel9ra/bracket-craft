/**
 * Modelo puro del observador de estados visibles (B1 de la validación).
 *
 * El escenario del navegador muestrea la interfaz cada 40 ms, pero una espera
 * (`waitFor`) observa el estado directamente y puede verlo durar menos que un
 * ciclo de muestreo. Este modelo separa las dos fuentes:
 *
 * - `sample`: el muestreo periódico, que solo registra un **cambio**.
 * - `observe`: la observación directa de una espera, que registra **siempre**
 *   una muestra con el instante real, aunque coincida con el último estado.
 *
 * La prueba reproduce el falso rojo observado entre los dos ciclos de pulsación
 * (el error dura menos que el intervalo, `latest` se queda en `retrying` y la
 * muestra del segundo ciclo no se registraba) y comprueba que ningún instante se
 * desplaza ni se inventa. Sin Playwright y sin leer el reloj: los estados y los
 * instantes entran por parámetro.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { createStatusModel } from '../e2e/statusObserver.ts';

test('sample registra solo los cambios de estado y descarta el silencio', () => {
  const model = createStatusModel();

  model.sample('connected', 0);
  model.sample('connected', 40);
  model.sample(null, 80);
  model.sample('error', 120);
  model.sample('error', 160);

  assert.deepEqual(model.samples(), [
    { status: 'connected', at: 0 },
    { status: 'error', at: 120 },
  ]);
  assert.equal(model.current(), 'error');
});

test('observe registra una muestra nueva aunque repita el último estado', () => {
  // Falso rojo de B1: entre ciclos el estado pasó por `error` menos de un ciclo
  // de muestreo, `latest` se quedó en `retrying` y el segundo clic se declaró
  // `manual-not-sampled` pese a que el producto sí mostró el estado manual.
  const model = createStatusModel();

  model.observe('retrying', 1_000); // ciclo 1: la espera vio el manual
  model.sample('retrying', 1_040); // el muestreo no repite el mismo estado
  model.observe('error', 1_500); // vuelve el error
  model.sample('error', 1_540);

  const clickedAt = 3_000; // segundo ciclo
  model.observe('retrying', 3_120);

  const manual = model.samples().filter((sample) => sample.status === 'retrying');
  assert.equal(manual.length, 2, 'cada ciclo deja su propia muestra del estado manual');
  const last = manual[1];
  assert.ok(last);
  assert.equal(last.at, 3_120);
  assert.ok(last.at >= clickedAt, 'la muestra del segundo ciclo es posterior a su clic');
});

test('un estado intermedio más corto que el intervalo de muestreo queda registrado', () => {
  const model = createStatusModel();

  model.sample('connected', 0);
  // El producto muestra `retrying` 10 ms y el bucle vuelve a mirar a los 40 ms.
  model.observe('retrying', 10);
  model.sample('error', 40);

  assert.deepEqual(model.samples(), [
    { status: 'connected', at: 0 },
    { status: 'retrying', at: 10 },
    { status: 'error', at: 40 },
  ]);
});

test('no se inventan instantes: se conserva el instante observado tal cual', () => {
  const model = createStatusModel();

  model.observe('retrying', 1_000);
  model.observe('retrying', 1_000); // misma milésima: no se desplaza a 1_001
  model.sample('error', 1_400);

  assert.deepEqual(model.samples(), [
    { status: 'retrying', at: 1_000 },
    { status: 'retrying', at: 1_000 },
    { status: 'error', at: 1_400 },
  ]);
});

test('firstChangeAfter devuelve la transición real posterior, sin fabricar marcas', () => {
  const model = createStatusModel();

  model.observe('retrying', 1_000);
  model.sample('error', 1_400);
  model.sample('retrying', 1_800);

  assert.deepEqual(model.firstChangeAfter('retrying', 1_000), {
    status: 'error',
    at: 1_400,
  });
  assert.deepEqual(model.firstChangeAfter('error', 1_400), {
    status: 'retrying',
    at: 1_800,
  });
  assert.equal(
    model.firstChangeAfter('retrying', 1_401),
    null,
    'una transición anterior al instante pedido no se reutiliza',
  );
});

test('el modelo no lee el reloj, no usa Playwright y no muta desde fuera', () => {
  const source = readFileSync(new URL('../e2e/statusObserver.ts', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /Date\.now|new Date|performance\.now|Math\.random/);
  assert.doesNotMatch(source, /@playwright\/test|node:fs/);

  const model = createStatusModel();
  model.observe('connected', 5);
  const exposed = model.samples();
  assert.equal(exposed.length, 1);
  // `samples()` entrega una copia: quien la lea no altera el observador.
  (exposed as { status: string; at: number }[]).push({ status: 'error', at: 9 });
  assert.equal(model.samples().length, 1);
});
