import { isForbidden, isUnauthorized } from '~/utils/api';
import { safeInternalRedirect } from '~/utils/navigation';
import type { RouteLocationNormalized } from 'vue-router';

export default defineNuxtRouteMiddleware(async (to: RouteLocationNormalized) => {
  const auth = useAuthStore();
  const { request } = useApi();

  if (!auth.userId) {
    return navigateTo({ path: '/login', query: { redirect: safeInternalRedirect(to.fullPath) } });
  }

  try {
    await request('/platform/users?limit=1');
  } catch (cause) {
    if (isUnauthorized(cause)) {
      await auth.logout();
      return navigateTo({ path: '/login', query: { redirect: safeInternalRedirect(to.fullPath) } });
    }
    if (isForbidden(cause)) {
      return navigateTo({ path: '/forbidden', query: { returnTo: safeInternalRedirect(to.fullPath), resource: 'admin' } });
    }
    throw cause;
  }
});
