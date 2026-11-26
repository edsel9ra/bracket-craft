import {
  exportErrorKey, exportFileName, exportLang, matchReportPath, tournamentExportPath, MATCH_REPORT_KIND,
  type ExportKind, type TournamentExportKind,
} from '~/utils/exports';

/** Descargas CSV del Workspace (spec 048, RF-001): una a la vez y siempre vía `useApi`. */
export function useExports() {
  const { request, organizationId } = useApi();
  const { t, locale } = useI18n();
  const busy = ref<ExportKind | null>(null);
  const error = ref('');
  const notice = ref('');
  let generation = 0;

  async function run(kind: ExportKind, path: string, name: string): Promise<boolean> {
    if (busy.value) return false;
    const token = generation;
    busy.value = kind; error.value = ''; notice.value = '';
    try {
      const blob = await request<Blob>(path, { query: { lang: exportLang(String(locale.value)) }, responseType: 'blob' });
      if (token !== generation) return false;
      const fileName = exportFileName(kind, name, new Date());
      saveExportFile(blob, fileName);
      notice.value = t('export.done', { file: fileName });
      return true;
    } catch (cause) {
      const key = await exportErrorKey(cause);
      if (token === generation) error.value = key;
      return false;
    } finally {
      if (token === generation) busy.value = null;
    }
  }

  function downloadTournament(tournamentId: string, kind: TournamentExportKind, tournamentName: string) {
    return run(kind, tournamentExportPath(tournamentId, kind), tournamentName);
  }

  function downloadMatchReport(matchId: string, matchName: string) {
    return run(MATCH_REPORT_KIND, matchReportPath(matchId), matchName);
  }

  function reset() {
    generation += 1;
    busy.value = null; error.value = ''; notice.value = '';
  }

  watch(() => organizationId.value, reset);
  onBeforeUnmount(() => { generation += 1; });

  return { busy, error, notice, downloadTournament, downloadMatchReport };
}
