/**
 * Aviso de cierre de inscripción (spec 012, RF-017, RF-039, P4/CI-1).
 *
 * **Copia deliberada de la regla del servidor.** El aviso replica en el cliente
 * la comprobación de `_active_roster_lock_matchday` en
 * `backend/app/modules/tournaments/router.py`. Se aceptó la duplicación (P4)
 * para no añadir un tercer cambio de contrato; su verificación es la
 * equivalencia con la respuesta real: cuando el aviso aparece, el alta responde
 * 409 con el mensaje de cierre; cuando no aparece, no hay 409 por ese motivo.
 *
 * El servidor sigue siendo la autoridad: esta réplica es informativa y nunca
 * impide ni sustituye la escritura; si el cliente se equivoca, se muestra el
 * mensaje del 409 real.
 *
 * Regla copiada, exactamente:
 * - la jornada de referencia sale de la versión **publicada más reciente**;
 * - la fase de referencia es la primera por `stage_order` (el `id` desempata);
 * - hay bloqueo si esa jornada de esa fase tiene al menos un partido no
 *   cancelado y **todos** están confirmados.
 *
 * Confirmado equivale a `finished` o `administrative_resolution`: el `CHECK`
 * `chk_terminal_result` de la base exige `result_confirmed = TRUE` para ambos
 * estados, y la lectura de partidos no expone `result_confirmed`.
 *
 * El módulo es puro: no lee el reloj, el entorno, el almacenamiento ni la red.
 */

export const ROSTER_LOCK_CONFIRMED_STATUSES: readonly string[] = [
  'finished',
  'administrative_resolution',
];

export interface RosterLockVersionLike {
  readonly id: string;
  readonly version_number: number;
  readonly status: string;
  readonly published_at?: string | null;
  readonly rules_config?: Record<string, unknown> | null;
}

export interface RosterLockStageLike {
  readonly id: string;
  readonly tournament_version_id?: string;
  readonly stage_order: number;
}

export interface RosterLockMatchLike {
  readonly id: string;
  readonly stage_id: string;
  readonly tournament_version_id?: string;
  readonly matchday: number | null;
  readonly status: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function toMatchday(value: unknown): number | null {
  if (typeof value === 'number') {
    return Number.isInteger(value) && value >= 1 ? value : null;
  }
  if (typeof value === 'string' && /^\d+$/.test(value.trim())) {
    const parsed = Number(value.trim());
    return Number.isInteger(parsed) && parsed >= 1 ? parsed : null;
  }
  return null;
}

/**
 * Jornada de referencia declarada, con el bloque deprecado como respaldo.
 * Misma semántica que `effective_roster_lock_matchday` en el backend.
 */
export function effectiveRosterLockMatchday(
  config: Record<string, unknown> | null | undefined,
): number | null {
  if (!isRecord(config)) return null;
  const topLevel = toMatchday(config.roster_lock_matchday);
  if (topLevel !== null) return topLevel;
  const transfers = config.transfers;
  return isRecord(transfers) ? toMatchday(transfers.roster_lock_matchday) : null;
}

/**
 * Versión publicada más reciente. Desempate estable sin reloj: `version_number`,
 * después `published_at` y, por último, el `id`.
 */
export function latestPublishedVersion<T extends RosterLockVersionLike>(
  versions: readonly T[],
): T | null {
  let latest: T | null = null;
  for (const version of versions) {
    if (version.status !== 'published') continue;
    if (latest === null) {
      latest = version;
      continue;
    }
    if (version.version_number !== latest.version_number) {
      if (version.version_number > latest.version_number) latest = version;
      continue;
    }
    const publishedAt = version.published_at || '';
    const latestPublishedAt = latest.published_at || '';
    if (publishedAt !== latestPublishedAt) {
      if (publishedAt > latestPublishedAt) latest = version;
      continue;
    }
    if (version.id > latest.id) latest = version;
  }
  return latest;
}

function firstStageByOrder(stages: readonly RosterLockStageLike[]): RosterLockStageLike | null {
  let first: RosterLockStageLike | null = null;
  for (const stage of stages) {
    if (first === null) {
      first = stage;
      continue;
    }
    if (stage.stage_order !== first.stage_order) {
      if (stage.stage_order < first.stage_order) first = stage;
      continue;
    }
    if (stage.id < first.id) first = stage;
  }
  return first;
}

/**
 * Jornada de cierre cuando el bloqueo está activo, o `null`.
 *
 * `stages` y `matches` son los de la versión publicada más reciente. La página
 * filtra por versión antes de llamar; la función no inventa ese contexto.
 */
export function rosterLockMatchday(
  config: Record<string, unknown> | null | undefined,
  stages: readonly RosterLockStageLike[],
  matches: readonly RosterLockMatchLike[],
): number | null {
  const matchday = effectiveRosterLockMatchday(config);
  if (matchday === null) return null;
  const referenceStage = firstStageByOrder(stages);
  if (referenceStage === null) return null;

  const relevant = matches.filter(
    (entry) => entry.stage_id === referenceStage.id
      && entry.matchday === matchday
      && entry.status !== 'cancelled',
  );
  if (relevant.length === 0) return null;
  return relevant.every((entry) => ROSTER_LOCK_CONFIRMED_STATUSES.includes(entry.status))
    ? matchday
    : null;
}

/** `true` cuando la jornada de referencia ya está cerrada. */
export function isRosterLockActive(
  config: Record<string, unknown> | null | undefined,
  stages: readonly RosterLockStageLike[],
  matches: readonly RosterLockMatchLike[],
): boolean {
  return rosterLockMatchday(config, stages, matches) !== null;
}
