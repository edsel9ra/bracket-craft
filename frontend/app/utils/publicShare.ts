/** Compartir público (spec 043 RF-011): hoja nativa → portapapeles → copia manual. */

export type ShareStrategy = 'native' | 'clipboard' | 'manual';
export type ShareOutcome = 'shared' | 'cancelled' | 'copied' | 'manual';

export interface SharePayload {
  title: string;
  url: string;
}

export interface ShareNavigator {
  share?: (data: SharePayload) => Promise<void>;
  clipboard?: { writeText?: (text: string) => Promise<void> };
}

export function shareStrategy(nav: ShareNavigator | undefined): ShareStrategy {
  if (typeof nav?.share === 'function') return 'native';
  if (typeof nav?.clipboard?.writeText === 'function') return 'clipboard';
  return 'manual';
}

function isAbort(cause: unknown): boolean {
  return typeof cause === 'object' && cause !== null && (cause as { name?: unknown }).name === 'AbortError';
}

export async function runShare(payload: SharePayload, nav: ShareNavigator | undefined): Promise<ShareOutcome> {
  if (shareStrategy(nav) === 'native') {
    try {
      await nav!.share!({ title: payload.title, url: payload.url });
      return 'shared';
    } catch (cause) {
      if (isAbort(cause)) return 'cancelled';
    }
  }
  if (typeof nav?.clipboard?.writeText === 'function') {
    try {
      await nav.clipboard.writeText(payload.url);
      return 'copied';
    } catch {
      return 'manual';
    }
  }
  return 'manual';
}
