export const WEBHOOK_EVENT_TYPES = ['match_scheduled', 'result_confirmed', 'walkover_declared', 'sanction_generated'] as const;
export const WEBHOOK_LIMIT = 10;
export const WEBHOOK_URL_MAX_LENGTH = 2048;

export type WebhookEventType = typeof WEBHOOK_EVENT_TYPES[number];
export type WebhookDeliveryType = WebhookEventType | 'webhook_test';
export type WebhookDeliveryStatus = 'pending' | 'delivered' | 'failed' | 'rejected' | 'discarded';

export interface WebhookItem {
  id: string;
  url: string;
  event_types: WebhookEventType[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CreatedWebhook extends WebhookItem {
  secret: string;
}

export interface WebhookInput {
  url: string;
  event_types: WebhookEventType[];
}

export interface WebhookDelivery {
  id: string;
  event_type: WebhookDeliveryType;
  created_at: string;
  attempts: number;
  last_status_code: number | null;
  status: WebhookDeliveryStatus;
}

interface ApiFailure {
  status?: number;
  statusCode?: number;
  data?: { detail?: unknown };
}

const URL_ERROR = 'webhook.error.url';

/** Espejo de `validate_url` del servidor: devuelve la clave del error o `null` si la URL es válida. */
export function validateWebhookUrl(url: string): string | null {
  const value = typeof url === 'string' ? url.trim() : '';
  if (!value || value.length > WEBHOOK_URL_MAX_LENGTH) return URL_ERROR;
  for (const char of value) {
    const code = char.charCodeAt(0);
    if (char.length > 1 || code < 0x21 || code > 0x7e) return URL_ERROR;
  }
  if (!/^https:\/\//i.test(value)) return URL_ERROR;
  const authority = value.slice(8).split(/[/?#]/, 1)[0] ?? '';
  if (!authority || authority.includes('@')) return URL_ERROR;
  try {
    const parsed = new URL(value);
    if (!parsed.hostname || parsed.username || parsed.password || parsed.port === '0') return URL_ERROR;
  } catch {
    return URL_ERROR;
  }
  return null;
}

/** Recorta la URL y deja el esquema en minúsculas, como la guarda el servidor. */
export function normalizeWebhookUrl(url: string): string {
  const value = url.trim();
  return /^https:/i.test(value) ? `https${value.slice(5)}` : value;
}

/** Tipos elegidos, sin duplicados y en el orden del catálogo. */
export function orderedWebhookTypes(types: readonly string[]): WebhookEventType[] {
  return WEBHOOK_EVENT_TYPES.filter((type) => types.includes(type));
}

export function webhookTypeKey(type: WebhookDeliveryType): string {
  return `webhook.type.${type}`;
}

export function deliveryStatusKey(status: WebhookDeliveryStatus): string {
  return `webhook.status.${status}`;
}

export function webhookErrorKey(cause: unknown): string {
  const failure = (cause ?? {}) as ApiFailure;
  const status = Number(failure.statusCode ?? failure.status);
  const detail = failure.data?.detail;
  if (status === 403) return 'webhook.error.forbidden';
  if (status === 404) return 'webhook.error.notFound';
  if (status === 409 && detail === 'WEBHOOK_LIMIT_REACHED') return 'webhook.error.limit';
  if (status === 409 && detail === 'WEBHOOK_INACTIVE') return 'webhook.error.inactive';
  if (status === 422) return URL_ERROR;
  return 'webhook.error.generic';
}
