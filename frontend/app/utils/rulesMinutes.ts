/**
 * Aviso de minutos al guardar las reglas de un borrador (spec 012, RF-035,
 * criterio 23; P2).
 *
 * Un cambio de `regular_time_minutes`/`extra_time_minutes` puede dejar fuera
 * del nuevo máximo registros que ya existen: **segmentos persistidos** (datos
 * del servidor, que no se corrigen porque no hay contrato de corrección) y
 * **eventos del borrador local** (que el operador puede corregir o retirar).
 * La spec exige **avisar antes de guardar**, sin borrar ni reescribir nada; el
 * guardado de las reglas nunca se bloquea por los eventos del borrador.
 *
 * El módulo es puro: no lee el reloj, el entorno, el almacenamiento ni la red.
 * Recibe los máximos efectivos de la configuración anterior y de la nueva, y
 * los registros ya cargados por la página.
 */

import { effectiveStageRules, type RulesConfig } from './rulesConfig.ts';
import type {
  ResolutionDraftEventInput,
  ResolutionSegmentInput,
} from './matchResolution.ts';

/** Máximos efectivos de una fase con una configuración concreta. */
export interface MinutesLimits {
  /** Minuto final reglamentario. */
  readonly regular: number;
  /** Minuto final con prórroga (se conserva aunque la prórroga esté apagada). */
  readonly extra: number;
  /** Si la prórroga está habilitada en la fase. */
  readonly extraEnabled: boolean;
}

/** Límites de una fase según la configuración (con su excepción si existe). */
export function minutesLimits(
  config: RulesConfig,
  stageId?: string | null,
): MinutesLimits {
  const effective = effectiveStageRules(config, stageId);
  return {
    regular: effective.regular_time_minutes,
    extra: effective.extra_time_minutes,
    extraEnabled: effective.extra_time_enabled,
  };
}

/** Partido cuyos registros se juzgan contra el cambio de minutos. */
export interface MinutesChangeSubject {
  readonly matchId: string;
  readonly previous: MinutesLimits;
  readonly next: MinutesLimits;
  /** Segmentos ya persistidos en el servidor (no corregibles, P2). */
  readonly segments?: readonly ResolutionSegmentInput[] | null;
  /** Eventos del borrador local (solo aviso). */
  readonly draftEvents?: readonly ResolutionDraftEventInput[] | null;
}

/** Un registro que queda fuera del nuevo máximo. */
export interface MinutesOutsideRecord {
  readonly matchId: string;
  readonly index: number;
  readonly minute: number;
  readonly addedMinute: number;
  /** Minutos que excede el máximo aplicable (nunca menor que 1). */
  readonly over: number;
  /** Máximo de resolución que excede. */
  readonly max: number;
  readonly resolution: 'regular' | 'extra_time';
}

/** Impacto agregado del cambio de minutos. */
export interface MinutesOutsideImpact {
  /** Segmentos persistidos fuera de límite: se avisan y nunca se reescriben. */
  readonly segments: readonly MinutesOutsideRecord[];
  /** Eventos del borrador fuera de límite: se avisan y nunca se borran. */
  readonly events: readonly MinutesOutsideRecord[];
  /** Partidos afectados, en el orden recibido y sin duplicados. */
  readonly matchIds: readonly string[];
  /** El máximo más pequeño superado, para el texto del aviso. */
  readonly maxMinute: number | null;
}

function integer(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.trunc(value) : 0;
}

/**
 * Exceso de un registro sobre un máximo (RF-032): más allá del minuto final o,
 * antes del final, cuando la suma con el minuto añadido lo pasa. En el minuto
 * final se admite el añadido dentro del tope estructural.
 */
function excess(minute: number, addedMinute: number, max: number): number {
  if (minute > max) return minute - max;
  if (minute === max) return 0;
  return Math.max(0, minute + addedMinute - max);
}

/**
 * Si el cambio reduce algún máximo efectivo. Si los minutos suben (o no
 * cambian), ningún registro puede quedar *nuevo* fuera de límite y no hay nada
 * que avisar.
 */
function reducesMaximum(previous: MinutesLimits, next: MinutesLimits): boolean {
  if (next.regular < previous.regular) return true;
  // Apagar la prórroga retira el máximo con prórroga aunque el valor se conserve.
  if (previous.extraEnabled && !next.extraEnabled) return true;
  if (previous.extraEnabled && next.extraEnabled && next.extra < previous.extra) return true;
  return false;
}

function exceededMaximum(
  minute: number,
  addedMinute: number,
  limits: MinutesLimits,
): Pick<MinutesOutsideRecord, 'over' | 'max' | 'resolution'> | null {
  const regularExcess = excess(minute, addedMinute, limits.regular);
  if (regularExcess <= 0) return null;
  if (limits.extraEnabled) {
    const extraExcess = excess(minute, addedMinute, limits.extra);
    if (extraExcess > 0) {
      return { over: extraExcess, max: limits.extra, resolution: 'extra_time' };
    }
  }
  return { over: regularExcess, max: limits.regular, resolution: 'regular' };
}

function segmentMinute(segment: ResolutionSegmentInput): number {
  const end = segment.minute_end;
  if (typeof end === 'number' && Number.isFinite(end)) return integer(end);
  return integer(segment.minute_start);
}

/**
 * Juzga un cambio de minutos contra los segmentos persistidos y los eventos del
 * borrador. Nunca modifica las listas recibidas: solo describe qué queda fuera
 * para que la pantalla avise antes de guardar.
 */
export function findMinutesOutside(
  subjects: readonly MinutesChangeSubject[],
): MinutesOutsideImpact {
  const segments: MinutesOutsideRecord[] = [];
  const events: MinutesOutsideRecord[] = [];
  const matchIds: string[] = [];

  for (const subject of subjects) {
    if (!reducesMaximum(subject.previous, subject.next)) continue;

    let affected = false;
    (subject.segments ?? []).forEach((segment, index) => {
      const minute = segmentMinute(segment);
      const exceeded = exceededMaximum(minute, 0, subject.next);
      if (!exceeded) return;
      affected = true;
      segments.push({
        matchId: subject.matchId,
        index,
        minute,
        addedMinute: 0,
        ...exceeded,
      });
    });

    (subject.draftEvents ?? []).forEach((event, index) => {
      const minute = integer(event.minute);
      const addedMinute = integer(event.added_minute);
      const exceeded = exceededMaximum(minute, addedMinute, subject.next);
      if (!exceeded) return;
      affected = true;
      events.push({
        matchId: subject.matchId,
        index,
        minute,
        addedMinute,
        ...exceeded,
      });
    });

    if (affected && !matchIds.includes(subject.matchId)) matchIds.push(subject.matchId);
  }

  const maximums = [...segments, ...events].map((record) => record.max);
  return {
    segments,
    events,
    matchIds,
    maxMinute: maximums.length ? Math.min(...maximums) : null,
  };
}
