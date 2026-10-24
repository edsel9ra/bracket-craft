// Navegación del torneo (spec 012, RF-018, RF-019, RF-020).
// Funciones puras: no leen el reloj, el entorno global ni el almacenamiento;
// toda la información entra como parámetro.

export type TournamentSection = 'summary' | 'configuration' | 'calendar' | 'rosters' | 'operation';

const TOURNAMENT_CALENDAR = /^\/workspace\/tournaments\/[^/]+\/calendar\/?$/;
const TOURNAMENT_ROSTERS = /^\/workspace\/tournaments\/[^/]+\/rosters\/?$/;
const MATCH_DETAIL = /^\/workspace\/matches\/([^/]+)\/?$/;

function pathnameOf(path: string): string {
  return path.split('?')[0]?.split('#')[0] ?? '';
}

function hashOf(path: string, hash: string): string {
  const normalized = hash || path.slice(path.indexOf('#'));
  return normalized.startsWith('#') ? normalized.slice(1) : normalized;
}

/**
 * Sección activa del índice del torneo.
 * Resumen y configuración comparten dirección, así que el fragmento distingue
 * entre ambos; el resto se deduce de la ruta.
 */
export function tournamentSectionForPath(path: string, hash = ''): TournamentSection {
  const pathname = pathnameOf(path);
  if (MATCH_DETAIL.test(pathname)) return 'operation';
  if (TOURNAMENT_CALENDAR.test(pathname)) return 'calendar';
  if (TOURNAMENT_ROSTERS.test(pathname)) return 'rosters';
  if (!pathname.startsWith('/workspace/tournaments/')) {
    // Fuera de un torneo no hay sección de torneo que marcar.
    return 'summary';
  }
  if (hashOf(path, hash).toLowerCase() === 'resumen') return 'summary';
  return 'configuration';
}

/** Identificador del partido cuando la dirección es la de su operación. */
export function matchIdFromPath(path: string): string | null {
  const match = pathnameOf(path).match(MATCH_DETAIL);
  return match?.[1] ? decodeURIComponent(match[1]) : null;
}

export interface TournamentSectionLinkContext {
  tournamentId: string;
  matchId?: string | null;
}

/**
 * Dirección real de cada sección. La operación solo existe con un partido en
 * contexto (RF-018); sin él se devuelve `null` y el índice no ofrece la entrada.
 */
export function tournamentSectionHref(
  section: TournamentSection,
  context: TournamentSectionLinkContext,
): string | null {
  const base = `/workspace/tournaments/${context.tournamentId}`;
  switch (section) {
    case 'summary':
      return `${base}#resumen`;
    case 'configuration':
      return `${base}#configuracion`;
    case 'calendar':
      return `${base}/calendar`;
    case 'rosters':
      return `${base}/rosters`;
    case 'operation':
      return context.matchId ? `/workspace/matches/${context.matchId}#operacion` : null;
  }
}

export interface LegacySectionRedirect {
  path: string;
  query: Record<string, string>;
  hash?: string;
  replace: true;
}

/**
 * Dirección nueva para un fragmento antiguo del torneo (RF-020).
 * `#calendario` y `#plantillas` redirigen a su sección; `#resumen`,
 * `#configuracion` y `#equipos` siguen resolviendo a su ancla. `#operacion`
 * sin partido lleva al listado de partidos del calendario, que es donde vive
 * ahora, sin inventar un partido. La redirección reemplaza la entrada de
 * historial para que «atrás» no rebote.
 */
export function legacySectionRedirect(
  tournamentId: string,
  hash: string,
  search = '',
): LegacySectionRedirect | null {
  const normalizedHash = (hash.startsWith('#') ? hash.slice(1) : hash).trim().toLowerCase();
  if (!normalizedHash) return null;

  const base = `/workspace/tournaments/${tournamentId}`;
  const stage = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search).get('stage');
  const query: Record<string, string> = stage ? { stage } : {};
  if (normalizedHash === 'calendario') {
    return { path: `${base}/calendar`, query, replace: true };
  }
  if (normalizedHash === 'operacion') {
    return { path: `${base}/calendar`, query, hash: '#operacion', replace: true };
  }
  if (normalizedHash === 'plantillas') {
    return { path: `${base}/rosters`, query: {}, replace: true };
  }
  return null;
}
