import assert from 'node:assert/strict';
import test from 'node:test';

import {
  FORMATION_OPTIONS,
  FORMATIONS_BY_GAME_FORMAT,
  FORMATIONS_GRID,
  formationGameFormat,
  formationOptionsFor,
  formationSlots,
  type FormationCode,
} from '../app/constants/formations.ts';
import { slotLine } from '../app/utils/publicLineup.ts';

// Spec 044, RF-001: mismas posiciones y orden que backend/app/modules/rule_contract.py.
const EXPECTED_SLOTS: Record<FormationCode, string[]> = {
  '4-3-3': ['GK', 'LB', 'LCB', 'RCB', 'RB', 'CM_L', 'CM', 'CM_R', 'LW', 'ST', 'RW'],
  '4-4-2': ['GK', 'LB', 'LCB', 'RCB', 'RB', 'LM', 'LCM', 'RCM', 'RM', 'ST_L', 'ST_R'],
  '3-5-2': ['GK', 'LCB', 'CB', 'RCB', 'LWB', 'LCM', 'CM', 'RCM', 'RWB', 'ST_L', 'ST_R'],
  '4-2-3-1': ['GK', 'LB', 'LCB', 'RCB', 'RB', 'CDM_L', 'CDM_R', 'LW', 'CAM', 'RW', 'ST'],
  '1-2-1': ['GK', 'CB', 'LM', 'RM', 'ST'],
  '2-1-1': ['GK', 'LCB', 'RCB', 'CM', 'ST'],
  '2-2': ['GK', 'LCB', 'RCB', 'ST_L', 'ST_R'],
  '2-3-1': ['GK', 'LCB', 'RCB', 'LM', 'CM', 'RM', 'ST'],
  '3-2-1': ['GK', 'LCB', 'CB', 'RCB', 'LCM', 'RCM', 'ST'],
  '3-1-2': ['GK', 'LCB', 'CB', 'RCB', 'CM', 'ST_L', 'ST_R'],
  '3-3-2': ['GK', 'LCB', 'CB', 'RCB', 'LM', 'CM', 'RM', 'ST_L', 'ST_R'],
  '3-4-1': ['GK', 'LCB', 'CB', 'RCB', 'LM', 'LCM', 'RCM', 'RM', 'ST'],
  '4-3-1': ['GK', 'LB', 'LCB', 'RCB', 'RB', 'CM_L', 'CM', 'CM_R', 'ST'],
};

const STARTERS = { '5v5': 5, '7v7': 7, '9v9': 9, '11v11': 11 } as const;

test('el catálogo por modalidad es el decidido en la spec 044 (DA-1)', () => {
  assert.deepEqual(FORMATIONS_BY_GAME_FORMAT, {
    '5v5': ['1-2-1', '2-1-1', '2-2'],
    '7v7': ['2-3-1', '3-2-1', '3-1-2'],
    '9v9': ['3-3-2', '3-4-1', '4-3-1'],
    '11v11': ['4-3-3', '4-4-2', '3-5-2', '4-2-3-1'],
  });
  assert.deepEqual(FORMATION_OPTIONS, ['4-3-3', '4-4-2', '3-5-2', '4-2-3-1']);
  assert.equal(Object.keys(FORMATIONS_GRID).length, 13);
});

test('cada formación tiene las posiciones del contrato, un único GK y los titulares de su modalidad', () => {
  for (const [format, codes] of Object.entries(FORMATIONS_BY_GAME_FORMAT)) {
    for (const code of codes) {
      const slots = formationSlots(code);
      assert.deepEqual(slots, EXPECTED_SLOTS[code], code);
      assert.equal(slots.length, STARTERS[format as keyof typeof STARTERS], code);
      assert.equal(slots.filter((slot) => slot === 'GK').length, 1, code);
      assert.equal(formationGameFormat(code), format, code);
    }
  }
});

test('formationOptionsFor ofrece solo la modalidad pedida y 11v11 si falta o es desconocida', () => {
  assert.deepEqual(formationOptionsFor('5v5'), ['1-2-1', '2-1-1', '2-2']);
  assert.deepEqual(formationOptionsFor('7v7'), ['2-3-1', '3-2-1', '3-1-2']);
  assert.deepEqual(formationOptionsFor('9v9'), ['3-3-2', '3-4-1', '4-3-1']);
  assert.deepEqual(formationOptionsFor('11v11'), FORMATION_OPTIONS);
  assert.deepEqual(formationOptionsFor(null), FORMATION_OPTIONS);
  assert.deepEqual(formationOptionsFor(undefined), FORMATION_OPTIONS);
  assert.deepEqual(formationOptionsFor('6v6'), FORMATION_OPTIONS);
});

test('formationGameFormat devuelve null para un código desconocido o vacío', () => {
  assert.equal(formationGameFormat('9-9-9'), null);
  assert.equal(formationGameFormat(''), null);
  assert.equal(formationGameFormat('__proto__'), null);
});

test('las coordenadas de las formaciones nuevas son las del plan §3', () => {
  assert.deepEqual(FORMATIONS_GRID['2-2'], {
    GK: { x: 50, y: 88 }, LCB: { x: 32, y: 70 }, RCB: { x: 68, y: 70 }, ST_L: { x: 35, y: 25 }, ST_R: { x: 65, y: 25 },
  });
  assert.deepEqual(FORMATIONS_GRID['4-3-1'], {
    GK: { x: 50, y: 88 }, LB: { x: 15, y: 70 }, LCB: { x: 38, y: 73 }, RCB: { x: 62, y: 73 }, RB: { x: 85, y: 70 },
    CM_L: { x: 29, y: 50 }, CM: { x: 50, y: 54 }, CM_R: { x: 71, y: 50 }, ST: { x: 50, y: 20 },
  });
});

test('las formaciones nuevas no solapan posiciones y respetan las bandas de slotLine', () => {
  const reduced = [
    ...FORMATIONS_BY_GAME_FORMAT['5v5'],
    ...FORMATIONS_BY_GAME_FORMAT['7v7'],
    ...FORMATIONS_BY_GAME_FORMAT['9v9'],
  ];
  for (const code of reduced) {
    const points = Object.entries(FORMATIONS_GRID[code]);
    for (let i = 0; i < points.length; i += 1) {
      const [slot, point] = points[i]!;
      assert.ok(point.x >= 0 && point.x <= 100 && point.y >= 0 && point.y <= 100, `${code} ${slot}`);
      if (slot === 'GK') assert.ok(point.y >= 85, `${code} GK`);
      else assert.notEqual(slotLine(code, slot), 'gk', `${code} ${slot}`);
      for (let j = i + 1; j < points.length; j += 1) {
        const [other, otherPoint] = points[j]!;
        const distance = Math.hypot(point.x - otherPoint.x, point.y - otherPoint.y);
        assert.ok(distance >= 10, `${code}: ${slot} y ${other} a ${distance.toFixed(1)}`);
      }
    }
  }
  assert.equal(slotLine('2-2', 'LCB'), 'def');
  assert.equal(slotLine('3-2-1', 'LCM'), 'mid');
  assert.equal(slotLine('1-2-1', 'ST'), 'att');
});
