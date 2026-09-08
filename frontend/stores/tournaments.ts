import { defineStore } from 'pinia';

export interface TournamentSummary {
  id: string;
  name: string;
  season: string;
  start_date: string;
  status: string;
  draft_version_id?: string | null;
}

export const useTournamentsStore = defineStore('tournaments', () => {
  const PAGE_SIZE = 50;
  const tournaments = ref<TournamentSummary[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const publicTournaments = ref<TournamentSummary[]>([]);
  const publicLoading = ref(false);
  const publicError = ref<string | null>(null);
  const hasMore = ref(false);
  const publicHasMore = ref(false);
  const { request, organizationId } = useApi();
  const { t, errorMessage } = useI18n();
  let loadGeneration = 0;

  async function load(options: { append?: boolean } = {}) {
    const append = options.append === true;
    const generation = ++loadGeneration;
    const requestOrganizationId = organizationId.value;
    const offset = append ? tournaments.value.length : 0;
    loading.value = true;
    if (!append) error.value = null;
    try {
      const result = await request<TournamentSummary[]>(`/tournaments?limit=${PAGE_SIZE}&offset=${offset}`);
      if (generation === loadGeneration && requestOrganizationId === organizationId.value) {
        tournaments.value = append ? [...tournaments.value, ...result] : result;
        hasMore.value = result.length === PAGE_SIZE;
      }
    } catch (cause) {
      if (generation === loadGeneration && requestOrganizationId === organizationId.value) {
        error.value = errorMessage(cause, t('workspace.noLoad'));
      }
      const failure = cause as { status?: number; statusCode?: number };
      if ((failure.status || failure.statusCode || 0) === 401 || (failure.status || failure.statusCode || 0) === 403) throw cause;
    } finally {
      if (generation === loadGeneration) loading.value = false;
    }
  }

  async function loadMore() {
    if (!hasMore.value || loading.value) return;
    await load({ append: true });
  }

  let publicLoadGeneration = 0;

  async function loadPublic(options: { append?: boolean } = {}) {
    const append = options.append === true;
    const generation = ++publicLoadGeneration;
    const offset = append ? publicTournaments.value.length : 0;
    publicLoading.value = true;
    if (!append) publicError.value = null;
    try {
      const result = await request<TournamentSummary[]>(`/tournaments/public?limit=${PAGE_SIZE}&offset=${offset}`);
      if (generation === publicLoadGeneration) {
        publicTournaments.value = append ? [...publicTournaments.value, ...result] : result;
        publicHasMore.value = result.length === PAGE_SIZE;
      }
    } catch (cause) {
      if (generation === publicLoadGeneration) publicError.value = errorMessage(cause, t('home.noPublicLoad'));
    } finally {
      if (generation === publicLoadGeneration) publicLoading.value = false;
    }
  }

  async function loadMorePublic() {
    if (!publicHasMore.value || publicLoading.value) return;
    await loadPublic({ append: true });
  }

  function clear() {
    loadGeneration += 1;
    tournaments.value = [];
    loading.value = false;
    error.value = null;
    hasMore.value = false;
  }

  return {
    tournaments,
    loading,
    error,
    publicTournaments,
    publicLoading,
    publicError,
    load,
    loadMore,
    loadPublic,
    loadMorePublic,
    hasMore,
    clear,
    publicHasMore,
  };
});
