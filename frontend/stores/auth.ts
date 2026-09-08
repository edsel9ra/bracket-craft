import { defineStore } from 'pinia';

import { useTournamentsStore } from './tournaments';
import { isNotFound, isUnauthorized } from '~/utils/api';
import { normalizeOrganizationId } from '~/utils/validation';

interface AuthResponse {
  access_token?: string | null;
  token_type: string;
  user_id: string;
  organization_id: string | null;
}

export interface OrganizationSummary {
  id: string;
  name: string;
  slug: string;
  organization_user_id: string;
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
  const loading = ref(false);
  const error = ref<string | null>(null);
  const sessionVersion = ref(0);

  const isAuthenticated = computed(() => Boolean(userId.value && organizationId.value));

  function saveSession(response: AuthResponse) {
    useTournamentsStore().clear();
    sessionVersion.value += 1;
    userId.value = response.user_id;
    organizationId.value = normalizeOrganizationId(response.organization_id);
  }

  function clearSession() {
    sessionVersion.value += 1;
    userId.value = null;
    organizationId.value = null;
    organizations.value = [];
    useTournamentsStore().clear();
  }

  async function loadOrganizations() {
    const result = await request<OrganizationSummary[]>('/organizations');
    organizations.value = result;
    if (!organizationId.value && result.length) {
      organizationId.value = result[0].id;
    }
    return result;
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
    loading,
    error,
    isAuthenticated,
    login,
    register,
    verifyWorkspace,
    loadOrganizations,
    logout,
  };
});
