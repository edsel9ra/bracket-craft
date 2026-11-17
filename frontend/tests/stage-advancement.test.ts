import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  ORIGIN_ERROR_CODES,
  PREVIEW_REASONS,
  RESOLUTION_ERROR_CODES,
  needsNewPreview,
  previewReasonKey,
  publicOriginLabel,
  resolutionErrorKey,
  emptyOrigin,
  isEliminationStage,
  originLabel,
  originsPayload,
  slotErrorKey,
  slotErrorsBySeed,
  slotsCountError,
  type SourceStage,
} from '../app/utils/stageAdvancement.ts';
import { catalogKeys } from '../app/utils/i18nCatalog.ts';

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');
const I18N = read('../app/composables/useI18n.ts');
const ENGLISH_START = I18N.indexOf('\n  en: {');
const SPANISH_KEYS = new Set(catalogKeys(I18N.slice(0, ENGLISH_START)));
const ENGLISH_KEYS = new Set(catalogKeys(I18N.slice(ENGLISH_START)));
const EDITOR = read('../app/components/workspace/setup/StageSlotOriginsEditor.vue');
const STAGES = read('../app/components/workspace/setup/SetupStages.vue');
const COMPOSABLE = read('../app/composables/useStageAdvancement.ts');
const PANEL = read('../app/components/workspace/setup/StageResolutionPanel.vue');

const GROUPS: SourceStage = {
  id: 'g', name: 'Grupos', stage_type: 'custom_group',
  groups: [{ id: 'a', name: 'A', size: 4 }, { id: 'b', name: 'B', size: 4 }],
};
const LEAGUE: SourceStage = { id: 'l', name: 'Liga', stage_type: 'round_robin', groups: [{ id: null, name: null, size: 6 }] };
const fake = (key: string, params: Record<string, unknown> = {}) =>
  `${key}${Object.keys(params).length ? JSON.stringify(params) : ''}`;

test('040 RF-001: solo las eliminatorias admiten orígenes', () => {
  assert.equal(isEliminationStage('single_elimination'), true);
  assert.equal(isEliminationStage('double_elimination'), true);
  for (const type of ['round_robin', 'custom_group', 'swiss', '', null, undefined]) {
    assert.equal(isEliminationStage(type as never), false, String(type));
  }
});

test('040 RF-002: etiquetas por grupo, tabla única y mejores N.º', () => {
  assert.equal(
    originLabel({ kind: 'group_position', source_stage_id: 'g', position: 1, group_id: 'a' }, [GROUPS], fake),
    'stageAdvancement.origin.groupPosition{"position":1,"group":"A"}',
  );
  assert.equal(
    originLabel({ kind: 'group_position', source_stage_id: 'l', position: 2, group_id: null }, [LEAGUE], fake),
    'stageAdvancement.origin.tablePosition{"position":2,"stage":"Liga"}',
  );
  assert.equal(
    originLabel({ kind: 'best_of_position', source_stage_id: 'g', position: 3, ordinal: 1 }, [GROUPS], fake),
    'stageAdvancement.origin.bestOfPosition{"position":3,"ordinal":1}',
  );
  assert.equal(
    originLabel({ kind: 'group_position', source_stage_id: 'x', position: 1, group_id: 'z' }, [GROUPS], fake),
    'stageAdvancement.origin.unknown',
  );
});

test('040 RF-002: el cuerpo enviado solo lleva los campos de cada tipo', () => {
  assert.deepEqual(originsPayload([
    { seed: 1, kind: 'group_position', source_stage_id: 'g', position: 1, group_id: 'a', ordinal: 4 },
    { seed: 2, kind: 'best_of_position', source_stage_id: 'g', position: 3, group_id: 'b', ordinal: 2 },
    { seed: 3, kind: 'group_position', source_stage_id: 'l', position: 2, group_id: null },
  ]), [
    { kind: 'group_position', source_stage_id: 'g', position: 1, group_id: 'a' },
    { kind: 'best_of_position', source_stage_id: 'g', position: 3, ordinal: 2 },
    { kind: 'group_position', source_stage_id: 'l', position: 2, group_id: null },
  ]);
  assert.deepEqual(emptyOrigin(GROUPS), { kind: 'group_position', source_stage_id: 'g', position: 1, group_id: 'a' });
  assert.deepEqual(emptyOrigin(LEAGUE), { kind: 'group_position', source_stage_id: 'l', position: 1, group_id: null });
});

test('040 CL-5: tamaño de la llave según el tipo de eliminatoria', () => {
  assert.equal(slotsCountError(2, 'single_elimination'), null);
  assert.equal(slotsCountError(6, 'single_elimination'), null);
  assert.equal(slotsCountError(64, 'single_elimination'), null);
  for (const value of [1, 65, 2.5, Number.NaN]) {
    assert.equal(slotsCountError(value, 'single_elimination'), 'stageAdvancement.slotsCountInvalid', String(value));
  }
  assert.equal(slotsCountError(8, 'double_elimination'), null);
  assert.equal(slotsCountError(6, 'double_elimination'), 'stageAdvancement.slotsCountPowerOfTwo');
});

test('040 RF-002: los errores del 422 se leen por plaza, sin valores enviados', () => {
  const failure = { statusCode: 422, data: { detail: { code: 'invalid_slot_origins', errors: [
    { seed: 2, code: 'group_not_found' }, { seed: 5, code: 'unequal_groups' }, { seed: null, code: 'invalid_slots_count' },
    { seed: 'x', code: 'duplicate_origin' }, { seed: 3, code: 7 },
  ] } } };
  assert.deepEqual(slotErrorsBySeed(failure), { 2: 'group_not_found', 5: 'unequal_groups' });
  assert.deepEqual(slotErrorsBySeed({ statusCode: 409, data: { detail: 'x' } }), {});
  assert.deepEqual(slotErrorsBySeed(null), {});
  for (const code of ORIGIN_ERROR_CODES) assert.equal(slotErrorKey(code), `stageAdvancement.error.${code}`);
  assert.equal(slotErrorKey('otro'), 'stageAdvancement.error.unknown');
});

test('040 RNF-004: cada clave usada existe en ES y EN', () => {
  const used = new Set<string>();
  for (const source of [EDITOR, PANEL, read('../app/utils/stageAdvancement.ts'), read('../app/components/public/PublicBracket.vue')]) {
    for (const match of source.matchAll(/'(stageAdvancement\.[A-Za-z0-9_.]+)'/g)) used.add(match[1]!);
  }
  for (const code of ORIGIN_ERROR_CODES) used.add(`stageAdvancement.error.${code}`);
  for (const reason of PREVIEW_REASONS) used.add(`stageAdvancement.reason.${reason}`);
  for (const code of RESOLUTION_ERROR_CODES) used.add(`stageAdvancement.resolutionError.${code}`);
  for (const status of ['editable', 'frozen', 'resolved']) used.add(`stageAdvancement.status.${status}`);
  for (const code of ['not_enough_teams', 'unequal_groups', 'invalid_source_stage', 'invalid_slots_count']) used.add(`stageAdvancement.templateError.${code}`);
  used.delete('stageAdvancement.error.');
  assert.ok(used.size > 20);
  for (const key of used) {
    assert.ok(SPANISH_KEYS.has(key), `falta en ES: ${key}`);
    assert.ok(ENGLISH_KEYS.has(key), `falta en EN: ${key}`);
  }
});

test('040 RF-001b: la plantilla rellena el borrador local y no se guarda sin acción del gestor', () => {
  assert.match(COMPOSABLE, /useApi\(\)/);
  assert.match(COMPOSABLE, /slot-origins`/);
  assert.match(COMPOSABLE, /\/template\?/);
  assert.doesNotMatch(COMPOSABLE, /\$fetch|fetch\(/);
  const applyTemplate = EDITOR.slice(EDITOR.indexOf('async function applyTemplate'), EDITOR.indexOf('async function save'));
  assert.match(applyTemplate, /api\.template\(/);
  assert.doesNotMatch(applyTemplate, /api\.(save|remove)\(/);
  assert.match(EDITOR, /@click="save"/);
  assert.match(EDITOR, /useConfirm\(\{ singleFlight: true \}\)/);
  assert.match(EDITOR, /aria-describedby/);
  assert.match(EDITOR, /role="alert"/);
});

test('040 RF-011: una llave con partidos y sin orígenes pide confirmar el reemplazo antes de guardar', () => {
  assert.match(EDITOR, /const replaceExisting = Boolean\(state\.value\?\.origins\.length\) \|\| props\.hasMatches;/);
  assert.match(EDITOR, /replace_existing: replaceExisting/);
  assert.match(read('../app/components/workspace/setup/SetupStages.vue'), /:has-matches="stageIdsWithMatches\?\.has\(stage\.id\) \?\? false"/);
  assert.match(read('../app/composables/useTournamentSetup.ts'), /stageIdsWithMatches = computed\(\(\) => new Set\(matches\.value\.map\(\(match\) => match\.stage_id\)\)\)/);
  assert.match(read('../app/pages/workspace/tournaments/[id]/index.vue'), /:stage-ids-with-matches="stageIdsWithMatches"/);
});

test('040 RF-003: el editor solo es editable en borrador y aparece para cada eliminatoria', () => {
  assert.match(EDITOR, /status === 'editable'/);
  assert.match(STAGES, /StageSlotOriginsEditor/);
  assert.match(STAGES, /isEliminationStage\(stage\.stage_type\)/);
});

test('040 RF-005/RF-006: motivos de bloqueo por plaza y errores de confirmación', () => {
  for (const reason of PREVIEW_REASONS) assert.equal(previewReasonKey(reason), `stageAdvancement.reason.${reason}`);
  assert.equal(previewReasonKey('otro'), 'stageAdvancement.reason.unknown');
  for (const code of RESOLUTION_ERROR_CODES) assert.equal(resolutionErrorKey(code), `stageAdvancement.resolutionError.${code}`);
  assert.equal(resolutionErrorKey(null), null);
  assert.equal(resolutionErrorKey('otro'), null);
  assert.equal(needsNewPreview('stale_fingerprint'), true);
  assert.equal(needsNewPreview('not_resolvable'), true);
  assert.equal(needsNewPreview('already_resolved'), false);
});

test('040 RF-003: sin permiso de gestión el panel publicado muestra los orígenes sin pedir la vista previa', () => {
  assert.match(PANEL, /if \(hasOrigins\.value && !resolved\.value && props\.canManage\) await loadPreview\(\);/);
  assert.match(PANEL, /<ul v-else-if="origins\.length" class="stage-resolution-origins">/);
  assert.match(PANEL, /originLabel\(origin, sources, t\)/);
});

test('040 RF-007/RF-008: el panel confirma con la huella de la vista previa y pide otra ante un 409', () => {
  assert.match(COMPOSABLE, /\/preview`/);
  assert.match(COMPOSABLE, /method: 'POST', body: \{ fingerprint \}/);
  assert.match(PANEL, /useConfirm\(\{ singleFlight: true \}\)/);
  assert.match(PANEL, /api\.confirmResolution\(props\.tournamentId, props\.stage\.id, current\.fingerprint\)/);
  assert.match(PANEL, /if \(needsNewPreview\(code\)\) await loadPreview\(\)/);
  assert.match(PANEL, /:disabled="busy \|\| !preview\.resolvable"/);
  assert.match(PANEL, /role="alert"/);
  assert.match(STAGES, /StageResolutionPanel/);
  assert.match(STAGES, /stage\.version_status === 'draft'/);
});

test('040 RF-009: la llave pública etiqueta las plazas sin resolver y deja de hacerlo al llenarse', () => {
  assert.equal(publicOriginLabel({ kind: 'group_position', group_name: 'A', position: 1, ordinal: null }, fake),
    'stageAdvancement.origin.groupPosition{"position":1,"group":"A"}');
  assert.equal(publicOriginLabel({ kind: 'group_position', group_name: null, position: 2, ordinal: null }, fake),
    'stageAdvancement.origin.publicTablePosition{"position":2}');
  assert.equal(publicOriginLabel({ kind: 'best_of_position', group_name: null, position: 3, ordinal: 1 }, fake),
    'stageAdvancement.origin.bestOfPosition{"position":3,"ordinal":1}');
  assert.equal(publicOriginLabel(null, fake), null);
  assert.equal(publicOriginLabel(undefined, fake), null);
  const bracket = read('../app/components/public/PublicBracket.vue');
  assert.match(bracket, /teamName \|\| shortCode \|\| publicOriginLabel\(origin, t\) \|\| t\('public\.toDefine'\)/);
  assert.match(bracket, /match\.home_origin/);
  assert.match(bracket, /match\.away_origin/);
});
