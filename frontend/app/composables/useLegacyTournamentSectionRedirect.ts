import { legacySectionRedirect } from '~/utils/tournamentNavigation';

/**
 * Redirige una dirección antigua con fragmento (`#calendario`, `#plantillas`)
 * a la sección con dirección propia (spec 012, RF-020), reemplazando la
 * entrada de historial para que «atrás» no vuelva a rebotar.
 *
 * Devuelve la función para poder ejecutarla en el arranque de la página
 * (servidor y cliente) y mantener el watch de los cambios de fragmento.
 */
export function useLegacyTournamentSectionRedirect(tournamentId: string) {
  const route = useRoute();

  async function redirectLegacyHash(): Promise<void> {
    const searchIndex = route.fullPath.indexOf('?');
    const search = searchIndex >= 0 ? route.fullPath.slice(searchIndex) : '';
    const target = legacySectionRedirect(tournamentId, route.hash, search);
    if (!target) return;
    await navigateTo({ path: target.path, query: target.query, hash: target.hash }, { replace: target.replace });
  }

  watch(() => route.hash, () => {
    void redirectLegacyHash();
  });

  return redirectLegacyHash;
}
