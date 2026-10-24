// Navegación de la operación del partido (spec 012, RF-022).
//
// Al operar un partido puede faltar un jugador: la pantalla enlaza a la
// plantilla del equipo —que es la única que da de alta jugadores (RF-021)— con
// contexto de retorno, y al volver se conservan el partido (la dirección), el
// segmento seleccionado y el borrador local de eventos y marcador.
//
// Funciones puras: no leen el reloj, el entorno global, el almacenamiento ni la
// red; toda la información entra como parámetro. Las que tocan el almacenamiento
// son los envoltorios de la página, probados con estas piezas.

/** Dirección de la operación del partido: el único destino de vuelta admitido. */
export function matchOperationPath(matchId: string): string {
  return `/workspace/matches/${encodeURIComponent(matchId)}#operacion`;
}

export interface TeamRosterLinkContext {
  readonly tournamentId: string;
  readonly teamId: string;
  readonly matchId: string;
}

/**
 * Dirección de la plantilla del equipo con contexto de retorno (RF-022).
 *
 * El retorno se construye aquí a partir del partido en contexto, nunca se
 * recibe de la dirección: no existe una redirección abierta y el destino solo
 * puede ser la operación interna de ese mismo partido. La pantalla de plantillas
 * conserva el parámetro al cambiar de equipo.
 */
export function teamRosterHref(context: TeamRosterLinkContext): string {
  const team = encodeURIComponent(context.teamId);
  const returnTo = encodeURIComponent(matchOperationPath(context.matchId));
  return `/workspace/tournaments/${context.tournamentId}/rosters?team=${team}&returnTo=${returnTo}`;
}

const INTERNAL_ORIGIN = 'https://bracket-craft.invalid';
const MATCH_PATH_PREFIX = '/workspace/matches/';

export interface RosterReturnContext {
  /** Torneo de la pantalla: el retorno nunca sale de su ámbito. */
  readonly tournamentId: string;
  /** Partidos de ese torneo cargados con el contexto de la organización activa. */
  readonly matchIds: readonly string[];
}

/**
 * Destino visible de «Volver a la operación» (RF-022), o `null` si no lo hay.
 *
 * El contexto de retorno llega por la dirección y por eso **no** se usa tal
 * cual: no hay redirección abierta. Solo se acepta una ruta interna de la
 * operación de un partido que esté entre los partidos del torneo cargados (el
 * endpoint ya filtra por organización y torneo), sin origen externo, sin barra
 * doble, sin barra invertida, sin parámetros y con el fragmento de operación o
 * ninguno. El destino devuelto se reconstruye aquí y no se copia del parámetro.
 *
 * `tournamentId` documenta el ámbito: la pertenencia al torneo y a la
 * organización la demuestra `matchIds`, que sale de
 * `/tournaments/{id}/matches` con el contexto de aislamiento de la transacción.
 */
export function rosterReturnHref(value: unknown, context: RosterReturnContext): string | null {
  if (typeof value !== 'string') return null;

  const candidate = value.trim();
  if (
    !candidate
    || candidate.length > 2048
    || !candidate.startsWith('/')
    || candidate.startsWith('//')
    || candidate.includes('\\')
    || /[\u0000-\u001f\u007f]/.test(candidate)
  ) {
    return null;
  }

  try {
    const decoded = decodeURIComponent(candidate);
    if (decoded.startsWith('//') || decoded.includes('\\') || /[\u0000-\u001f\u007f]/.test(decoded)) {
      return null;
    }
  } catch {
    return null;
  }

  let parsed: URL;
  try {
    parsed = new URL(candidate, INTERNAL_ORIGIN);
  } catch {
    return null;
  }
  if (parsed.origin !== INTERNAL_ORIGIN) return null;
  if (parsed.search) return null;
  if (parsed.hash && parsed.hash !== '#operacion') return null;
  if (!parsed.pathname.startsWith(MATCH_PATH_PREFIX)) return null;

  const matchId = parsed.pathname.slice(MATCH_PATH_PREFIX.length);
  if (!matchId || matchId.includes('/')) return null;
  if (!context.matchIds.includes(matchId)) return null;

  return matchOperationPath(matchId);
}

export interface MatchSelectionScope {
  readonly userId: string;
  readonly organizationId: string;
  readonly matchId: string;
}

/** Clave del segmento seleccionado: por usuario, organización y partido. */
export function matchSelectionKey(scope: MatchSelectionScope): string {
  return `bc_match_selection:${scope.userId}:${scope.organizationId}:${scope.matchId}`;
}

/** Valor guardado del segmento seleccionado. */
export function writeMatchSelection(segmentId: string): string {
  return JSON.stringify({ version: 1, segment_id: segmentId });
}

/**
 * Segmento guardado que todavía existe en el partido. Cualquier valor ilegible,
 * de otra forma o de un segmento que ya no está se descarta sin romper la
 * pantalla: la operación vuelve a su selección por defecto.
 */
export function readMatchSelection(
  raw: string | null | undefined,
  segmentIds: readonly string[],
): string | null {
  if (!raw) return null;
  try {
    const saved = JSON.parse(raw) as { segment_id?: unknown };
    const segmentId = saved?.segment_id;
    return typeof segmentId === 'string' && segmentIds.includes(segmentId) ? segmentId : null;
  } catch {
    return null;
  }
}
