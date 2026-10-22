import { defineStore } from 'pinia';

import { useTournamentsStore } from './tournaments';
import { isNotFound, isUnauthorized } from '~/utils/api';
import { organizationHistoryEntry, selectActiveOrganization } from '~/utils/organizationSelection';
import { normalizeOrganizationId } from '~/utils/validation';

interface AuthResponse {
  user_id: string;
  organization_id: string | null;
}

const ORGANIZATION_HISTORY_KEY = 'bc_last_organization_id';

function readRememberedOrganization(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return normalizeOrganizationId(window.localStorage.getItem(ORGANIZATION_HISTORY_KEY));
  } catch {
    return null;
  }
}

function writeRememberedOrganization(organizationId: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(ORGANIZATION_HISTORY_KEY, organizationId);
  } catch {
    // Sin almacenamiento local no hay historial: el orden estable sigue decidiendo.
  }
}

export interface OrganizationSummary {
  id: string;
  name: string;
  slug: string;
  organization_user_id: string;
}

export interface OrganizationAccess {
  organization_id: string;
  organization_user_id: string;
  user_id: string;
  role_code: 'owner' | 'administrator' | 'operator' | 'referee' | 'viewer' | string;
  permissions: string[];
}

interface ApiFailure {
  status?: number;
  statusCode?: number;
  data?: {
    detail?: string | Array<{ loc?: Array<string | number>; msg?: string }>;
  };
}

function getFailureMessage(cause: unknown, fallback: string, invalidSlugMessage: string, errorMessage: (cause: unknown, fallback: string) => string): string {
  const failure = cause as ApiFailure;
  const detail = failure.data?.detail;
  if (Array.isArray(detail)) {
    const validation = detail[0];
    if (validation?.loc?.includes('organization_slug')) {
      return invalidSlugMessage;
    }
  }
  return errorMessage(cause, fallback);
}

export const useAuthStore = defineStore('auth', () => {
  const { request, organizationId } = useApi();
  const { t, errorMessage } = useI18n();
  const userId = useCookie<string | null>('bc_user_id', {
    sameSite: 'lax',
    secure: !import.meta.dev,
  });
  const organizations = ref<OrganizationSummary[]>([]);
  const access = ref<OrganizationAccess | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const sessionVersion = ref(0);
  const rememberedOrganizationId = ref<string | null>(readRememberedOrganization());

  const isAuthenticated = computed(() => Boolean(userId.value && organizationId.value));

  /**
   * El historial del navegador solo guarda una organización que la persona
   * puede activar en este momento. Se escribe al cambiar de organización en el
   * Workspace y al fijarse una activa cuando todavía no había historial.
   */
  function rememberActiveOrganization(candidate: string | null) {
    const entry = organizationHistoryEntry(organizations.value, candidate);
    if (!entry || entry === rememberedOrganizationId.value) return;
    rememberedOrganizationId.value = entry;
    writeRememberedOrganization(entry);
  }

  watch(organizationId, (next) => rememberActiveOrganization(next), { flush: 'sync' });

  function saveSession(response: AuthResponse) {
    useTournamentsStore().clear();
    sessionVersion.value += 1;
    organizations.value = [];
    userId.value = response.user_id;
    organizationId.value = normalizeOrganizationId(response.organization_id);
    access.value = null;
  }

  async function adoptSession(response: AuthResponse) {
    saveSession(response);
    // Aceptar una invitación es elegir esa organización de forma explícita: si
    // sigue siendo accesible, prevalece sobre el historial del navegador.
    await loadOrganizations({ preferredOrganizationId: response.organization_id });
  }

  function clearSession() {
    sessionVersion.value += 1;
    userId.value = null;
    organizationId.value = null;
    organizations.value = [];
    access.value = null;
    useTournamentsStore().clear();
  }

  async function loadOrganizations(options: { preferredOrganizationId?: string | null } = {}) {
    const result = await request<OrganizationSummary[]>('/organizations');
    organizations.value = result;
    const preferred = normalizeOrganizationId(options.preferredOrganizationId);
    const remembered = preferred ?? rememberedOrganizationId.value ?? readRememberedOrganization();
    const selected = selectActiveOrganization(result, remembered);
    organizationId.value = selected?.id ?? null;
    if (selected) rememberActiveOrganization(selected.id);
    if (organizationId.value) await loadAccess();
    return result;
  }

  async function loadAccess() {
    if (!organizationId.value) {
      access.value = null;
      return null;
    }
    access.value = await request<OrganizationAccess>('/organizations/current/access');
    return access.value;
  }

  function hasPermission(permission: string): boolean {
    return Boolean(access.value?.permissions.includes(permission));
  }

  async function login(email: string, password: string) {
    loading.value = true;
    error.value = null;
    try {
      const response = await request<AuthResponse>('/auth/login', {
        method: 'POST',
        body: { email, password },
      });
      saveSession(response);
      await loadOrganizations();
      return response;
    } catch (cause) {
      error.value = getFailureMessage(cause, t('auth.noLogin'), t('auth.invalidSlug'), errorMessage);
      throw cause;
    } finally {
      loading.value = false;
    }
  }

  async function register(payload: {
    email: string;
    password: string;
    full_name: string;
    organization_name: string;
    organization_slug: string;
  }) {
    loading.value = true;
    error.value = null;
    try {
      const response = await request<AuthResponse>('/auth/register', {
        method: 'POST',
        body: payload,
      });
      saveSession(response);
      await loadOrganizations();
      return response;
    } catch (cause) {
      error.value = getFailureMessage(cause, t('auth.noRegister'), t('auth.invalidSlug'), errorMessage);
      throw cause;
    } finally {
      loading.value = false;
    }
  }

  async function verifyWorkspace() {
    if (!userId.value) throw new Error(t('error.authRequired'));
    if (!organizationId.value) await loadOrganizations();
    if (!organizationId.value) throw new Error(t('auth.noActiveOrganization'));

    try {
      await request('/organizations/current');
      if (!organizations.value.length) await loadOrganizations();
      await loadAccess();
    } catch (cause) {
      if (isUnauthorized(cause) || isNotFound(cause)) clearSession();
      throw cause;
    }
  }

  async function logout() {
    try {
      await request('/auth/logout', { method: 'POST' });
    } catch {
      // La sesión local debe limpiarse aunque el servidor ya no la reconozca.
    }
    clearSession();
  }

  return {
    userId,
    organizationId,
    sessionVersion,
    organizations,
    access,
    loading,
    error,
    isAuthenticated,
    login,
    register,
    verifyWorkspace,
    loadOrganizations,
    loadAccess,
    hasPermission,
    logout,
    adoptSession,
  };
});
