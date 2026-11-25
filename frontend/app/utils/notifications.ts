export const NOTIFICATION_TYPES = ['match_scheduled', 'result_confirmed', 'walkover_declared', 'sanction_generated'] as const;
export const NOTIFICATION_CHANNELS = ['inbox', 'email'] as const;
export const NOTIFICATION_PAGE_SIZE = 25;

export type NotificationType = typeof NOTIFICATION_TYPES[number];
export type NotificationChannel = typeof NOTIFICATION_CHANNELS[number];
type Translate = (key: string, values?: Record<string, string | number>) => string;

export interface NotificationSanction {
  player_name: string | null;
  team_name: string | null;
  matches_suspended: number;
}

export interface NotificationItem {
  id: string;
  type: NotificationType;
  created_at: string;
  read_at: string | null;
  tournament_id: string;
  tournament_name: string;
  match_id: string | null;
  home_team_name: string | null;
  away_team_name: string | null;
  match_count: number | null;
  sanction: NotificationSanction | null;
}

export interface NotificationPage {
  items: NotificationItem[];
  unread_count: number;
  total: number;
  limit: number;
  offset: number;
}

export interface NotificationPreference {
  type: NotificationType;
  channel: NotificationChannel;
  enabled: boolean;
}

export function notificationTypeKey(type: NotificationType): string {
  return `notification.type.${type}`;
}

export function notificationLink(item: NotificationItem): string {
  if (item.match_id) return `/workspace/matches/${item.match_id}`;
  return `/workspace/tournaments/${item.tournament_id}/calendar`;
}

export function notificationSummary(item: NotificationItem, t: Translate): string {
  if (!item.match_id) return t('notification.summary.scheduled', { count: item.match_count ?? 0 });
  return t('notification.summary.match', { home: item.home_team_name || t('notification.tbd'), away: item.away_team_name || t('notification.tbd') });
}

/** Solo hay detalle si la API lo envía, es decir, si el miembro tiene `VIEW_SANCTION_CASES` (046, DA-5). */
export function sanctionSummary(item: NotificationItem, t: Translate): string {
  if (!item.sanction) return '';
  return t('notification.summary.sanction', {
    player: item.sanction.player_name || t('notification.unknownPlayer'),
    team: item.sanction.team_name || t('notification.tbd'),
    count: item.sanction.matches_suspended,
  });
}

export function notificationQuery(page: { limit: number; offset: number }): string {
  return `?limit=${page.limit}&offset=${page.offset}`;
}

export function notificationErrorKey(cause: unknown): string {
  const failure = cause as { status?: number; statusCode?: number } | null;
  const status = failure?.statusCode || failure?.status;
  if (status === 403) return 'notification.error.forbidden';
  if (status === 404) return 'notification.error.notFound';
  if (status === 422) return 'notification.error.invalid';
  return 'notification.error.generic';
}

export function orderedPreferences(items: readonly NotificationPreference[]): NotificationPreference[] {
  return NOTIFICATION_TYPES.flatMap((type) => NOTIFICATION_CHANNELS.map((channel) => {
    const saved = items.find((item) => item.type === type && item.channel === channel);
    return { type, channel, enabled: saved ? saved.enabled === true : channel === 'inbox' };
  }));
}
