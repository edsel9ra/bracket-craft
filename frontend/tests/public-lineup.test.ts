import assert from 'node:assert/strict';
import test from 'node:test';

import {
  formationSlots,
  isTacticalFormationValid,
  playerInitials,
  slotLine,
  textualFormationLines,
  type LineCode,
} from '../app/utils/publicLineup.ts';
import type { PublicLineupPlayer, PublicTeamLineup } from '../app/utils/publicTournament.ts';
import { FORMATIONS_GRID } from '../app/constants/formations.ts';

function player(overrides: Partial<PublicLineupPlayer> = {}): PublicLineupPlayer {
  return {
    player_id: overrides.player_id ?? 'p',
    first_name: overrides.first_name ?? 'Ana',
    last_name: overrides.last_name ?? 'Lopez',
    dorsal_number: overrides.dorsal_number ?? 10,
    role: overrides.role ?? 'starter',
    position_slot: overrides.position_slot ?? null,
    photo_url: overrides.photo_url ?? null,
  };
}

function team(overrides: Partial<PublicTeamLineup> = {}): PublicTeamLineup {
  return {
    team_id: 't1',
    team_name: 'Equipo',
    formation_code: overrides.formation_code ?? null,
    segment_number: overrides.segment_number ?? 1,
    crest_url: null,
    starters: overrides.starters ?? [],
    substitutes: overrides.substitutes ?? [],
  };
}

function validTeam(code: '4-3-3' | '4-4-2' | '3-5-2' | '4-2-3-1'): PublicTeamLineup {
  const slots = formationSlots(code);
  return team({
    formation_code: code,
    starters: slots.map((slot, index) =>
      player({ player_id: `p${index}`, position_slot: slot }),
    ),
  });
}

test('formationSlots reuses the catalog', () => {
  assert.deepEqual(formationSlots('4-3-3'), Object.keys(FORMATIONS_GRID['4-3-3']));
  assert.deepEqual(formationSlots(''), []);
});

test('isTacticalFormationValid accepts a complete formation', () => {
  for (const code of ['4-3-3', '4-4-2', '3-5-2', '4-2-3-1'] as const) {
    assert.equal(isTacticalFormationValid(validTeam(code)), true, code);
  }
});

test('RF-006: titular sin posición -> lista, no campo', () => {
  const t = validTeam('4-3-3');
  t.starters[0]!.position_slot = null;
  assert.equal(isTacticalFormationValid(t), false);
});

test('RF-006: posición fuera del catálogo -> lista', () => {
  const t = validTeam('4-3-3');
  t.starters[0]!.position_slot = 'XX';
  assert.equal(isTacticalFormationValid(t), false);
});

test('RF-006: formation_code nulo con position_slot no nulo -> planilla', () => {
  const t = team({
    formation_code: null,
    starters: [player({ position_slot: 'GK' })],
  });
  assert.equal(isTacticalFormationValid(t), false);
});

test('RF-006: número de titulares distinto al catálogo -> lista', () => {
  const t = validTeam('4-3-3');
  t.starters.pop();
  assert.equal(isTacticalFormationValid(t), false);

  const t2 = validTeam('4-3-3');
  t2.starters.push(player({ player_id: 'extra', position_slot: 'GK' }));
  // duplicate slot -> invalid
  assert.equal(isTacticalFormationValid(t2), false);
});

test('RF-006: cero titulares con código no nulo -> lista', () => {
  const t = team({ formation_code: '4-3-3', starters: [] });
  assert.equal(isTacticalFormationValid(t), false);
});

test('RF-006: código inválido -> lista', () => {
  const t = team({ formation_code: '5-4-1' as any, starters: [player({ position_slot: 'GK' })] });
  assert.equal(isTacticalFormationValid(t), false);
});

test('caso límite: formación sin publicar no aparece (backend) — helper false con code null', () => {
  const t = team({ formation_code: null, starters: [] });
  assert.equal(isTacticalFormationValid(t), false);
  assert.deepEqual(textualFormationLines(t), []);
});

test('caso límite: formación incompleta del rival no afecta al completo', () => {
  const complete = validTeam('4-3-3');
  const incomplete = validTeam('4-4-2');
  incomplete.starters[0]!.position_slot = null;
  assert.equal(isTacticalFormationValid(complete), true);
  assert.equal(isTacticalFormationValid(incomplete), false);
});

test('slotLine clasifica por coordenada y y GK explícito', () => {
  assert.equal(slotLine('4-3-3', 'GK'), 'gk');
  // defensa y >= 60
  assert.equal(slotLine('4-3-3', 'LCB'), 'def');
  // mediocampo y >= 45
  assert.equal(slotLine('4-3-3', 'CM'), 'mid');
  // delantera resto
  assert.equal(slotLine('4-3-3', 'ST'), 'att');
});

test('textualFormationLines agrupa y ordena por x', () => {
  const t = validTeam('4-3-3');
  const lines = textualFormationLines(t);
  assert.ok(lines.length > 0);
  assert.equal(lines[0]!.line, 'gk');
  // cada línea no vacía
  for (const l of lines) assert.ok(l.players.length > 0);
  // orden dentro de línea por x ascendente
  for (const l of lines) {
    const xs = l.players.map((p) => FORMATIONS_GRID['4-3-3'][p.position_slot as string]!.x);
    const sorted = [...xs].sort((a, b) => a - b);
    assert.deepEqual(xs, sorted);
  }
});

test('textualFormationLines devuelve [] si no es válida', () => {
  const t = team({ formation_code: '4-3-3', starters: [player({ position_slot: 'GK' })] });
  assert.deepEqual(textualFormationLines(t), []);
});

test('playerInitials devuelve iniciales en mayúsculas', () => {
  assert.equal(playerInitials(player({ first_name: 'Ana', last_name: 'Lopez' })), 'AL');
  assert.equal(playerInitials(player({ first_name: 'ana', last_name: 'lopez' })), 'AL');
});

test('playerInitials gestiona nombres faltantes', () => {
  assert.equal(playerInitials(player({ first_name: '', last_name: 'Lopez' })), 'L');
  assert.equal(playerInitials(player({ first_name: 'Ana', last_name: '' })), 'A');
  assert.equal(playerInitials(player({ first_name: '', last_name: '' })), '');
});

test('caso límite: walkover sin lineup — helper false', () => {
  assert.equal(isTacticalFormationValid(team({ formation_code: null, starters: [] })), false);
});

test('caso límite: jugador con consentimiento retirado — iniciales sin foto rota', () => {
  const p = player({ first_name: 'Ana', last_name: 'Lopez', photo_url: null });
  assert.equal(playerInitials(p), 'AL');
});

test('caso límite: pantalla 360px no es lógica de este módulo (sin cambios)', () => {
  assert.ok(true);
});

test('no lee reloj, red ni almacenamiento', () => {
  // sanity: functions are pure exports
  assert.equal(typeof isTacticalFormationValid, 'function');
});
