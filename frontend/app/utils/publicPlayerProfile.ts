/**
 * Contrato y funciones puras de la ficha pública de jugador (spec 038).
 */

export interface PublicPlayerProfileTotals {
  matches_played: number;
  goals: number;
  yellow_cards: number;
  red_cards: number;
  clean_sheets: number;
  minutes_played: number;
  penalties_saved: number;
}

export interface PublicPlayerProfileTournament extends PublicPlayerProfileTotals {
  tournament_id: string;
  tournament_name: string;
  team_id: string;
  team_name: string;
  main_position: MainPosition | null;
}

export interface PublicPlayerProfile {
  player_id: string;
  first_name: string;
  last_name: string;
  photo_url: string | null;
  totals: PublicPlayerProfileTotals;
  tournaments: PublicPlayerProfileTournament[];
}

type NamedPlayer = { first_name?: unknown; last_name?: unknown };

/** RF-005: las cinco cifras de la 022, en el orden de la tabla. */
export const PROFILE_STAT_FIELDS: readonly { key: keyof PublicPlayerProfileTotals; label: string }[] = [
  { key: 'matches_played', label: 'public.played' },
  { key: 'goals', label: 'public.goals' },
  { key: 'yellow_cards', label: 'public.yellowCards' },
  { key: 'red_cards', label: 'public.redCards' },
  { key: 'clean_sheets', label: 'public.cleanSheets' },
  { key: 'minutes_played', label: 'public.minutesPlayed' },
  { key: 'penalties_saved', label: 'public.penaltiesSaved' },
];

/** Spec 052 RF-002: línea estable que devuelve la API y su texto ES/EN. */
export type MainPosition = 'goalkeeper' | 'defender' | 'midfielder' | 'forward';

export const MAIN_POSITION_LABEL_KEYS: Readonly<Record<MainPosition, string>> = {
  goalkeeper: 'public.mainLine.goalkeeper',
  defender: 'public.mainLine.defender',
  midfielder: 'public.mainLine.midfielder',
  forward: 'public.mainLine.forward',
};

export function mainPositionLabel(value: unknown, translate: (key: string) => string): string {
  if (typeof value !== 'string' || !Object.hasOwn(MAIN_POSITION_LABEL_KEYS, value)) return '—';
  return translate(MAIN_POSITION_LABEL_KEYS[value as MainPosition]);
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isPlayerProfileId(value: unknown): value is string {
  return typeof value === 'string' && UUID_PATTERN.test(value);
}

export function playerProfilePath(playerId: string): string {
  return `/players/${encodeURIComponent(playerId)}`;
}

export function playerProfileApiPath(playerId: string): string {
  return `/tournaments/public/players/${encodeURIComponent(playerId)}`;
}

/** RF-009: el nombre enlaza solo si la inscripción de este torneo está autorizada. */
export function profileLinkFor(
  player: { player_id?: unknown; profile_available?: unknown } | null | undefined,
): string | null {
  if (!player || player.profile_available !== true || !isPlayerProfileId(player.player_id)) return null;
  return playerProfilePath(player.player_id);
}

function namePart(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

export function playerProfileName(player: NamedPlayer): string {
  return [namePart(player.first_name), namePart(player.last_name)].filter(Boolean).join(' ');
}

export function playerProfileInitials(player: NamedPlayer): string {
  return [namePart(player.first_name), namePart(player.last_name)]
    .map((part) => part.charAt(0).toUpperCase())
    .join('');
}

/** RF-007: sin foto, o si la URL ya falló, se muestran iniciales. */
export function profilePhotoVisible(
  profile: { photo_url?: string | null },
  failedUrl: string | null,
): boolean {
  const url = typeof profile.photo_url === 'string' ? profile.photo_url.trim() : '';
  return url !== '' && url !== failedUrl;
}
