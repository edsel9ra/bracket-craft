/**
 * Contrato y funciones puras de la cronología pública del partido (spec 037).
 */

import type { PublicMatch } from './publicTournament.ts';

export type PublicTimelineAvailability = 'pending' | 'not_played' | 'available';
export type PublicTimelineEventType =
  | 'goal'
  | 'penalty_goal'
  | 'own_goal'
  | 'yellow_card'
  | 'red_card'
  | 'substitution';
export type PublicRedCardType = 'direct_red' | 'double_yellow_red';

export interface PublicTimelinePlayer {
  player_id: string;
  first_name: string;
  last_name: string;
  profile_available?: boolean;
}

export interface PublicTimelineEvent {
  event_type: PublicTimelineEventType;
  minute: number;
  added_minute: number;
  segment_number: number;
  team_id: string;
  beneficiary_team_id: string | null;
  red_card_type: PublicRedCardType | null;
  player: PublicTimelinePlayer;
  player_in: PublicTimelinePlayer | null;
}

export interface PublicMatchTimeline {
  match_id: string;
  availability: PublicTimelineAvailability;
  score_consistent: boolean;
  segment_numbers: number[];
  events: PublicTimelineEvent[];
}

export interface PublicTimelineGroup {
  segmentNumber: number;
  showSeparator: boolean;
  events: PublicTimelineEvent[];
}

export type PublicTimelineSide = 'home' | 'away';

type ReloadFields = Pick<PublicMatch, 'status' | 'home_score' | 'away_score' | 'rectified_at'> & {
  home_penalties?: number | null;
  away_penalties?: number | null;
};

const EVENT_KEYS: Record<PublicTimelineEventType, string> = {
  goal: 'publicTimeline.event.goal',
  penalty_goal: 'publicTimeline.event.penaltyGoal',
  own_goal: 'publicTimeline.event.ownGoal',
  yellow_card: 'publicTimeline.event.yellowCard',
  red_card: 'publicTimeline.event.redCard',
  substitution: 'publicTimeline.event.substitution',
};

const RED_CARD_KEYS: Record<PublicRedCardType, string> = {
  direct_red: 'publicTimeline.event.directRed',
  double_yellow_red: 'publicTimeline.event.doubleYellowRed',
};

/** Solo los partidos cerrados ofrecen la cronología (RF-001, RF-002). */
export function canOpenTimeline(match: Pick<PublicMatch, 'status'> | null | undefined): boolean {
  return match?.status === 'finished';
}

/** Minuto público: `37'` o `45+2'` (RF-009). */
export function formatTimelineMinute(minute: number, addedMinute = 0): string {
  const base = Math.max(0, Math.trunc(Number(minute) || 0));
  const added = Math.max(0, Math.trunc(Number(addedMinute) || 0));
  return added > 0 ? `${base}+${added}'` : `${base}'`;
}

/** Clave i18n por tipo; la roja sin clasificar se queda en «roja» sin inferir (RF-008). */
export function timelineEventKey(event: Pick<PublicTimelineEvent, 'event_type' | 'red_card_type'>): string {
  if (event.event_type === 'red_card' && event.red_card_type) {
    return RED_CARD_KEYS[event.red_card_type] ?? EVENT_KEYS.red_card;
  }
  return EVENT_KEYS[event.event_type];
}

export function timelinePlayerName(player: PublicTimelinePlayer | null | undefined): string {
  if (!player) return '';
  return [player.first_name, player.last_name]
    .map((part) => (typeof part === 'string' ? part.trim() : ''))
    .filter(Boolean)
    .join(' ');
}

export function timelineEventSide(
  event: Pick<PublicTimelineEvent, 'team_id'>,
  match: Pick<PublicMatch, 'home_team_id' | 'away_team_id'>,
): PublicTimelineSide | null {
  if (event.team_id && event.team_id === match.home_team_id) return 'home';
  if (event.team_id && event.team_id === match.away_team_id) return 'away';
  return null;
}

/**
 * Lista única agrupada por segmento; el separador solo aparece con más de un
 * segmento (DA-4), también en los segmentos sin hechos (CL-13). Sin ningún
 * hecho no hay grupos: el componente muestra el estado vacío. Conserva el
 * orden del servidor dentro de cada segmento.
 */
export function timelineGroups(timeline: Pick<PublicMatchTimeline, 'segment_numbers' | 'events'>): PublicTimelineGroup[] {
  const events = Array.isArray(timeline.events) ? timeline.events : [];
  const numbers = new Set<number>(Array.isArray(timeline.segment_numbers) ? timeline.segment_numbers : []);
  for (const event of events) numbers.add(event.segment_number);
  if (!events.length) return [];
  const showSeparator = numbers.size > 1;
  return [...numbers]
    .sort((a, b) => a - b)
    .map((segmentNumber) => ({
      segmentNumber,
      showSeparator,
      events: events.filter((event) => event.segment_number === segmentNumber),
    }));
}

/** El diálogo abierto se recarga si el refresco público cambia el partido (RF-014). */
export function shouldReloadTimeline(
  previous: ReloadFields | null | undefined,
  next: ReloadFields | null | undefined,
): boolean {
  if (!previous || !next) return previous !== next;
  return (
    previous.status !== next.status ||
    previous.home_score !== next.home_score ||
    previous.away_score !== next.away_score ||
    (previous.home_penalties ?? null) !== (next.home_penalties ?? null) ||
    (previous.away_penalties ?? null) !== (next.away_penalties ?? null) ||
    (previous.rectified_at ?? null) !== (next.rectified_at ?? null)
  );
}
