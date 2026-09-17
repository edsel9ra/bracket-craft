import { isForbidden, isNotFound, isUnauthorized } from '~/utils/api';
import { safeInternalRedirect } from '~/utils/navigation';
import type { RouteLocationNormalized } from 'vue-router';

export default defineNuxtRouteMiddleware(async (to: RouteLocationNormalized) => {
  const auth = useAuthStore();
  const { organizationId } = useApi();

  if (!auth.userId || !organizationId.value) {
    return navigateTo({
      path: '/login',
      query: { redirect: safeInternalRedirect(to.fullPath) },
    });
  }

  try {
    await useApi().request('/organizations/current');
    await auth.loadAccess();
  } catch (cause) {
    if (isUnauthorized(cause) || isNotFound(cause)) {
      await auth.logout();
      return navigateTo({ path: '/login', query: { redirect: safeInternalRedirect(to.fullPath) } });
    }
    if (isForbidden(cause)) {
      return navigateTo({ path: '/forbidden', query: { returnTo: safeInternalRedirect(to.fullPath), resource: 'workspace' } });
    }
    throw cause;
  }
});
