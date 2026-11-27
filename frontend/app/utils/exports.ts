/** Utilidades puras de las exportaciones CSV (spec 048) y PDF (spec 050) del Workspace. */

export const TOURNAMENT_EXPORT_KINDS = ['standings', 'calendar', 'player-stats', 'team-stats', 'rosters'] as const;
export const MATCH_REPORT_KIND = 'match-report' as const;
export const EXPORT_MAX_ROWS = 10_000;
/** Solo la descarga de plantillas queda en la auditoría de la organización (RF-007). */
export const AUDITED_EXPORT_KINDS: readonly string[] = ['rosters'];

export const EXPORT_FORMATS = ['csv', 'pdf'] as const;
/** Espejo de `PDF_KINDS` del backend: solo la clasificación y el acta tienen PDF (spec 050, DA-1). */
export const PDF_EXPORT_KINDS = ['standings', MATCH_REPORT_KIND] as const;

export type TournamentExportKind = typeof TOURNAMENT_EXPORT_KINDS[number];
export type ExportKind = TournamentExportKind | typeof MATCH_REPORT_KIND;
export type ExportFormat = typeof EXPORT_FORMATS[number];
export type ExportLang = 'es' | 'en';

export function hasPdf(kind: ExportKind): boolean {
  return (PDF_EXPORT_KINDS as readonly string[]).includes(kind);
}

function formatSuffix(kind: ExportKind, format: ExportFormat): string {
  if (format === 'csv') return '';
  if (!hasPdf(kind)) throw new Error(`${kind} has no pdf export`);
  return '/pdf';
}

const NAME_LIMIT = 60;

export function tournamentExportPath(tournamentId: string, kind: TournamentExportKind, format: ExportFormat = 'csv'): string {
  return `/tournaments/${encodeURIComponent(tournamentId)}/exports/${kind}${formatSuffix(kind, format)}`;
}

export function matchReportPath(matchId: string, format: ExportFormat = 'csv'): string {
  return `/matches/${encodeURIComponent(matchId)}/export${formatSuffix(MATCH_REPORT_KIND, format)}`;
}

export function exportLang(locale: string): ExportLang {
  return locale === 'en' ? 'en' : 'es';
}

function asciiSlug(value: string): string {
  return value.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, NAME_LIMIT).replace(/-+$/g, '');
}

/** Nombre del archivo en ASCII; la fecha llega como parámetro (no se lee el reloj aquí). */
// Sin el nombre cargado, el archivo lleva el prefijo del ID, como el del backend.
export function exportSubject(name: string | null | undefined, id: string): string {
  return name?.trim() || id.slice(0, 8);
}

export function exportFileName(kind: ExportKind, name: string, date: Date, format: ExportFormat = 'csv'): string {
  const slug = asciiSlug(name);
  const day = date.toISOString().slice(0, 10);
  return slug ? `${kind}-${slug}-${day}.${format}` : `${kind}-${day}.${format}`;
}

export function exportBusyKey(kind: ExportKind, format: ExportFormat): string {
  return `${kind}:${format}`;
}

export function exportDownloadKey(format: ExportFormat): string {
  return format === 'pdf' ? 'export.downloadPdf' : 'export.download';
}

export function matchReportTitleKey(format: ExportFormat): string {
  return format === 'pdf' ? 'export.kind.match-report.pdfTitle' : 'export.kind.match-report.title';
}

export function exportTitleKey(kind: ExportKind): string {
  return `export.kind.${kind}.title`;
}

export function exportDescriptionKey(kind: ExportKind): string {
  return `export.kind.${kind}.description`;
}

interface ApiFailure {
  status?: number;
  statusCode?: number;
  data?: unknown;
}

async function errorDetail(data: unknown): Promise<unknown> {
  // Con `responseType: 'blob'` el cuerpo del error también llega como Blob.
  if (typeof Blob !== 'undefined' && data instanceof Blob) {
    try {
      return (JSON.parse(await data.text()) as { detail?: unknown })?.detail;
    } catch {
      return undefined;
    }
  }
  return (data as { detail?: unknown } | null | undefined)?.detail;
}

export async function exportErrorKey(cause: unknown): Promise<string> {
  const failure = (cause ?? {}) as ApiFailure;
  const status = Number(failure.statusCode ?? failure.status);
  if (status === 404) return 'export.error.notFound';
  const detail = await errorDetail(failure.data);
  if (status === 409 && detail === 'MATCH_NOT_CLOSED') return 'export.error.notClosed';
  if (status === 422 && detail === 'EXPORT_TOO_LARGE') return 'export.error.tooLarge';
  return 'export.error.generic';
}
