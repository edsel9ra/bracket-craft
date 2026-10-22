/**
 * Descubrimiento de los datos de la corrida (RF-003, caso límite 16).
 *
 * El arnés no fija UUID ni escribe datos: descubre por la API **pública** un
 * torneo publicado con eventos (al menos un partido cerrado) y un partido
 * abierto (`scheduled`) con sus dos equipos para la operación. Si el seed demo
 * no ofrece datos utilizables, falla como **infraestructura/datos** y nunca
 * omite una vista. No consume `v_public_tournament_players` ni inyecta cookies:
 * las peticiones son de solo lectura y sin sesión.
 */

import type { DemoIdentifiers } from './observations.ts';

/** Cuenta y organización ficticias de desarrollo (`scripts.seed_demo`). */
export const DEMO_EMAIL = 'demo.owner@bracketcraft.dev';
export const DEMO_PASSWORD = 'Demo1234!';
export const DEMO_ORGANIZATION = 'demo-federation';

/** API pública local por defecto; el job usa el mismo valor documentado. */
export const DEMO_API_BASE = 'http://localhost:8000/api/v1';

export interface DemoCredentials {
  readonly email: string;
  readonly password: string;
}

/**
 * Credenciales por entorno con los valores **de desarrollo** por defecto. No hay
 * secretos en el repositorio: estos datos ya están documentados en `AGENTS.md`
 * y solo existen en la base desechable del seed.
 */
export function demoCredentials(
  env: Record<string, string | undefined> = process.env,
): DemoCredentials {
  const email = env.E2E_EMAIL?.trim();
  const password = env.E2E_PASSWORD;
  return {
    email: email ? email : DEMO_EMAIL,
    password: password && password.length > 0 ? password : DEMO_PASSWORD,
  };
}

/** Base de la API por entorno; sin barra final para concatenar rutas. */
export function demoApiBase(env: Record<string, string | undefined> = process.env): string {
  const configured = env.E2E_API_BASE?.trim();
  return (configured ? configured : DEMO_API_BASE).replace(/\/+$/, '');
}

/**
 * Datos utilizables que no existen o no se pueden leer. El runner lo traduce a
 * fallo de **infraestructura** (2), nunca a corrida inválida ni a vista omitida.
 */
export class DemoDataError extends Error {
  readonly kind = 'infrastructure' as const;

  constructor(message: string) {
    super(message);
    this.name = 'DemoDataError';
  }
}

export interface DemoTournament {
  readonly id: string;
  readonly name: string;
  readonly status: string;
}

export interface DemoMatch {
  readonly id: string;
  readonly status: string;
  readonly home_team_id: string | null;
  readonly away_team_id: string | null;
}

/** Un torneo público ya emparejado con sus partidos públicos. */
export interface DemoTournamentCandidate {
  readonly tournament: DemoTournament;
  readonly matches: readonly DemoMatch[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function readString(row: Record<string, unknown>, key: string): string | null {
  const value = row[key];
  return typeof value === 'string' ? value : null;
}

function parseTournaments(payload: unknown): DemoTournament[] {
  if (!Array.isArray(payload)) {
    throw new DemoDataError('la lista pública de torneos no es una lista');
  }
  const tournaments: DemoTournament[] = [];
  for (const row of payload) {
    if (!isRecord(row)) continue;
    const id = readString(row, 'id');
    if (!id) continue;
    tournaments.push({
      id,
      name: readString(row, 'name') ?? '',
      status: readString(row, 'status') ?? '',
    });
  }
  return tournaments;
}

function parseMatches(payload: unknown): DemoMatch[] {
  if (!Array.isArray(payload)) {
    throw new DemoDataError('la lista pública de partidos no es una lista');
  }
  const matches: DemoMatch[] = [];
  for (const row of payload) {
    if (!isRecord(row)) continue;
    const id = readString(row, 'id');
    if (!id) continue;
    matches.push({
      id,
      status: readString(row, 'status') ?? '',
      home_team_id: readString(row, 'home_team_id'),
      away_team_id: readString(row, 'away_team_id'),
    });
  }
  return matches;
}

/** Un partido es ejecutable en la operación si está abierto y tiene dos equipos. */
export function isOpenMatch(match: DemoMatch): boolean {
  return (
    match.status === 'scheduled' && match.home_team_id !== null && match.away_team_id !== null
  );
}

/**
 * Elige el primer torneo con **eventos** públicos (un partido cerrado) y un
 * partido abierto con equipos. Los torneos `live` se prueban primero y el orden
 * de la API se conserva dentro de cada grupo, así que la elección es estable
 * entre corridas. Devuelve `null` cuando los datos no permiten ejecutar la
 * vista de la operación (caso límite 16).
 */
export function selectDemoIdentifiers(
  candidates: readonly DemoTournamentCandidate[],
): DemoIdentifiers | null {
  const ordered = [...candidates].sort(
    (left, right) =>
      Number(right.tournament.status === 'live') - Number(left.tournament.status === 'live'),
  );

  for (const candidate of ordered) {
    const hasEvents = candidate.matches.some((match) => match.status === 'finished');
    const openMatch = candidate.matches.find(isOpenMatch);
    if (hasEvents && openMatch) {
      return { tournamentId: candidate.tournament.id, matchId: openMatch.id };
    }
  }

  return null;
}

async function getJson(fetchImpl: typeof fetch, url: string): Promise<unknown> {
  let response: Response;
  try {
    response = await fetchImpl(url, { headers: { accept: 'application/json' } });
  } catch (cause) {
    const detail = cause instanceof Error ? cause.message : String(cause);
    throw new DemoDataError(`no se pudo consultar ${url}: ${detail}`);
  }
  if (!response.ok) {
    throw new DemoDataError(`${url} respondió ${response.status}`);
  }
  return (await response.json()) as unknown;
}

export interface DiscoverDemoDataOptions {
  readonly apiBase?: string;
  readonly fetchImpl?: typeof fetch;
}

/**
 * Descubre por la API pública el torneo y el partido de la corrida. Solo lee:
 * no crea, no publica y no toca la base. Un fallo de red o unos datos sin
 * partido abierto se declaran como `DemoDataError` (infraestructura) con la
 * causa y la pista del seed de desarrollo.
 */
export async function discoverDemoData(
  options: DiscoverDemoDataOptions = {},
): Promise<DemoIdentifiers> {
  const apiBase = (options.apiBase ?? demoApiBase()).replace(/\/+$/, '');
  const fetchImpl = options.fetchImpl ?? fetch;

  const tournaments = parseTournaments(
    await getJson(fetchImpl, `${apiBase}/tournaments/public`),
  );
  if (tournaments.length === 0) {
    throw new DemoDataError(
      'no hay torneos públicos: ejecuta `docker compose exec -T api python -m scripts.seed_demo`',
    );
  }

  const candidates: DemoTournamentCandidate[] = [];
  for (const tournament of tournaments) {
    const matches = parseMatches(
      await getJson(
        fetchImpl,
        `${apiBase}/tournaments/public/${encodeURIComponent(tournament.id)}/matches`,
      ),
    );
    candidates.push({ tournament, matches });
  }

  const identifiers = selectDemoIdentifiers(candidates);
  if (!identifiers) {
    throw new DemoDataError(
      'los datos demo no ofrecen un torneo con eventos y un partido abierto (`scheduled`) con equipos: ejecuta `docker compose exec -T api python -m scripts.seed_demo`',
    );
  }
  return identifiers;
}
