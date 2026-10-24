import { safeInternalRedirect } from '~/utils/navigation';
import type { RouteLocationNormalized } from 'vue-router';

/**
 * Exige una sesión para las pantallas nuevas de cuenta y organización.
 *
 * No sustituye a `middleware/auth.ts` (que sigue protegiendo el Workspace y
 * valida organización y acceso): aquí solo se comprueba `userId`, porque
 * `/organization` debe ser accesible con sesión y sin organización.
 */
export default defineNuxtRouteMiddleware((to: RouteLocationNormalized) => {
  const auth = useAuthStore();
  if (auth.userId) return;

  return navigateTo({
    path: '/login',
    query: { redirect: safeInternalRedirect(to.fullPath) },
  });
});
