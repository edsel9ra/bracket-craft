import { isForbidden, isNotFound, isUnauthorized } from '~/utils/api';
import { safeInternalRedirect } from '~/utils/navigation';

export default defineNuxtRouteMiddleware(async (to) => {
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
