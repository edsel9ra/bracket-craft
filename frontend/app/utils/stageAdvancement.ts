/** Modelo puro del editor de orígenes de plaza (spec 040, F2). */

import type { PublicSlotOrigin } from './publicTournament';

export type OriginKind = 'group_position' | 'best_of_position';

export interface SlotOrigin {
  seed?: number;
  kind: OriginKind;
  source_stage_id: string;
  position: number;
  group_id?: string | null;
  ordinal?: number | null;
}

export interface SourceGroup {
  id: string | null;
  name: string | null;
  size: number;
}

export interface SourceStage {
  id: string;
  name: string;
  stage_type: string;
  groups: SourceGroup[];
}

export interface SlotOriginsState {
  stage_id: string;
  stage_type: string;
  status: 'editable' | 'frozen' | 'resolved';
  origins: SlotOrigin[];
  source_stages: SourceStage[];
}

export type Translate = (key: string, params?: Record<string, string | number>) => string;

export const MIN_SLOTS = 2;
export const MAX_SLOTS = 64;

export const ORIGIN_ERROR_CODES = [
  'invalid_source_stage', 'group_required', 'group_not_found', 'position_out_of_range',
  'unequal_groups', 'ordinal_out_of_range', 'duplicate_origin', 'overlapping_origin',
] as const;

export function isEliminationStage(stageType: string | null | undefined): boolean {
  return stageType === 'single_elimination' || stageType === 'double_elimination';
}

export function slotsCountError(count: number, stageType: string): string | null {
  if (!Number.isInteger(count) || count < MIN_SLOTS || count > MAX_SLOTS) return 'stageAdvancement.slotsCountInvalid';
  if (stageType === 'double_elimination' && (count & (count - 1)) !== 0) return 'stageAdvancement.slotsCountPowerOfTwo';
  return null;
}

export function originLabel(origin: SlotOrigin, sources: readonly SourceStage[], t: Translate): string {
  const stage = sources.find((item) => item.id === origin.source_stage_id);
  if (!stage) return t('stageAdvancement.origin.unknown');
  if (origin.kind === 'best_of_position') {
    return t('stageAdvancement.origin.bestOfPosition', { position: origin.position, ordinal: origin.ordinal ?? 0 });
  }
  const group = stage.groups.find((item) => item.id === (origin.group_id ?? null));
  if (!group) return t('stageAdvancement.origin.unknown');
  if (group.id === null) return t('stageAdvancement.origin.tablePosition', { position: origin.position, stage: stage.name });
  return t('stageAdvancement.origin.groupPosition', { position: origin.position, group: group.name ?? '' });
}

export function emptyOrigin(stage: SourceStage): SlotOrigin {
  return { kind: 'group_position', source_stage_id: stage.id, position: 1, group_id: stage.groups[0]?.id ?? null };
}

export function originsPayload(origins: readonly SlotOrigin[]): SlotOrigin[] {
  return origins.map((origin) => origin.kind === 'best_of_position'
    ? { kind: origin.kind, source_stage_id: origin.source_stage_id, position: origin.position, ordinal: origin.ordinal ?? null }
    : { kind: origin.kind, source_stage_id: origin.source_stage_id, position: origin.position, group_id: origin.group_id ?? null });
}

/** Errores por plaza (`seed` 1-based) del 422 `invalid_slot_origins`; ignora todo lo que no tenga esa forma. */
export function slotErrorsBySeed(cause: unknown): Record<number, string> {
  const detail = (cause as { data?: { detail?: unknown } } | null)?.data?.detail;
  if (!detail || typeof detail !== 'object') return {};
  const { code, errors } = detail as { code?: unknown; errors?: unknown };
  if (code !== 'invalid_slot_origins' || !Array.isArray(errors)) return {};
  const result: Record<number, string> = {};
  for (const item of errors) {
    const { seed, code: itemCode } = (item ?? {}) as { seed?: unknown; code?: unknown };
    if (Number.isInteger(seed) && typeof itemCode === 'string') result[seed as number] = itemCode;
  }
  return result;
}

export function slotErrorKey(code: string): string {
  return (ORIGIN_ERROR_CODES as readonly string[]).includes(code)
    ? `stageAdvancement.error.${code}`
    : 'stageAdvancement.error.unknown';
}

/** Código de error de la llave completa (`data.detail.code`), por ejemplo `not_enough_teams`. */
export function stageAdvancementErrorCode(cause: unknown): string | null {
  const detail = (cause as { data?: { detail?: unknown } } | null)?.data?.detail;
  if (!detail || typeof detail !== 'object') return null;
  const code = (detail as { code?: unknown }).code;
  return typeof code === 'string' ? code : null;
}

export interface SlotPreview extends SlotOrigin {
  seed: number;
  team_id: string | null;
  team_name: string | null;
  reason: string | null;
}

export interface ResolutionPreview {
  stage_id: string;
  fingerprint: string;
  resolvable: boolean;
  slots: SlotPreview[];
  source_stages: Array<{ id: string; finished: boolean }>;
}

export const PREVIEW_REASONS = [
  'invalid_source_stage', 'source_stage_unfinished', 'group_not_found', 'position_missing',
  'unresolved_tie', 'unequal_groups', 'team_ineligible', 'duplicate_team',
] as const;

export const RESOLUTION_ERROR_CODES = [
  'stale_fingerprint', 'already_resolved', 'version_not_published', 'not_resolvable', 'no_slot_origins',
] as const;

export function previewReasonKey(reason: string): string {
  return (PREVIEW_REASONS as readonly string[]).includes(reason)
    ? `stageAdvancement.reason.${reason}`
    : 'stageAdvancement.reason.unknown';
}

export function resolutionErrorKey(code: string | null): string | null {
  return code && (RESOLUTION_ERROR_CODES as readonly string[]).includes(code) ? `stageAdvancement.resolutionError.${code}` : null;
}

/** Un 409 de huella obsoleta exige una vista previa nueva antes de volver a confirmar (RF-008). */
export function needsNewPreview(code: string | null): boolean {
  return code === 'stale_fingerprint' || code === 'not_resolvable';
}

/** Etiqueta pública de una plaza sin resolver (RF-009); sin origen, `null` y la llave usa «Por definir». */
export function publicOriginLabel(origin: PublicSlotOrigin | null | undefined, t: Translate): string | null {
  if (!origin) return null;
  if (origin.kind === 'best_of_position') {
    return t('stageAdvancement.origin.bestOfPosition', { position: origin.position, ordinal: origin.ordinal ?? 0 });
  }
  return origin.group_name
    ? t('stageAdvancement.origin.groupPosition', { position: origin.position, group: origin.group_name })
    : t('stageAdvancement.origin.publicTablePosition', { position: origin.position });
}
