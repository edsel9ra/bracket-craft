import {
  assignableMembers, sortTeam, tournamentTeamErrorKey,
  type OrganizationMember, type TournamentTeamMember,
} from '~/utils/tournamentTeam';

/** «Equipo del torneo» (spec 049, RF-003, RF-004, RF-012): lectura para miembros, cambios con MANAGE_MEMBERS. */
export function useTournamentTeam(tournamentId: () => string) {
  const { request, organizationId } = useApi();
  const auth = useAuthStore();
  const { t } = useI18n();
  const { confirm } = useConfirm({ singleFlight: true });
  const canManage = computed(() => Boolean(
    auth.hasPermission('MANAGE_MEMBERS') && organizationId.value && organizationId.value === auth.access?.organization_id,
  ));
  const items = ref<TournamentTeamMember[]>([]);
  const members = ref<OrganizationMember[]>([]);
  const candidates = computed(() => assignableMembers(members.value, items.value));
  const loading = ref(false);
  const busy = ref(false);
  const error = ref('');
  const actionError = ref('');
  const notice = ref('');
  let generation = 0;

  const base = () => `/tournaments/${encodeURIComponent(tournamentId())}/team`;
  const memberPath = (id: string) => `${base()}/${encodeURIComponent(id)}`;

  function reset() {
    generation += 1;
    items.value = []; members.value = []; error.value = ''; actionError.value = ''; notice.value = '';
    loading.value = false; busy.value = false;
  }

  async function load() {
    const token = generation;
    loading.value = true; error.value = '';
    try {
      const [team, organizationMembers] = await Promise.all([
        request<TournamentTeamMember[]>(base()),
        canManage.value ? request<OrganizationMember[]>('/organizations/members') : Promise.resolve([]),
      ]);
      if (token !== generation) return;
      items.value = sortTeam(team);
      members.value = assignableMembers(organizationMembers, []);
    } catch (cause) {
      if (token === generation) error.value = tournamentTeamErrorKey(cause);
    } finally {
      if (token === generation) loading.value = false;
    }
  }

  async function run(action: () => Promise<unknown>, noticeKey: string, memberId: string): Promise<boolean> {
    if (!canManage.value || busy.value) return false;
    const token = generation;
    busy.value = true; actionError.value = ''; notice.value = '';
    try {
      await action();
      if (token !== generation) return false;
      notice.value = noticeKey;
      if (memberId === auth.access?.organization_user_id) await auth.loadAccess();
      await load();
      return true;
    } catch (cause) {
      if (token === generation) actionError.value = tournamentTeamErrorKey(cause);
      return false;
    } finally {
      if (token === generation) busy.value = false;
    }
  }

  async function assign(memberId: string) {
    if (!memberId) return false;
    return run(() => request<TournamentTeamMember>(memberPath(memberId), { method: 'PUT' }), 'tournamentTeam.assigned', memberId);
  }

  async function remove(item: TournamentTeamMember) {
    if (!canManage.value || busy.value) return false;
    const accepted = await confirm({
      title: t('tournamentTeam.confirm.remove.title'),
      message: t('tournamentTeam.confirm.remove.message', { name: item.full_name }),
      confirmLabel: t('tournamentTeam.confirm.remove.action'),
      tone: 'danger',
    });
    if (!accepted) return false;
    return run(() => request<null>(memberPath(item.organization_user_id), { method: 'DELETE' }), 'tournamentTeam.removed', item.organization_user_id);
  }

  watch(() => [organizationId.value, auth.userId, auth.access?.organization_id, tournamentId()], () => { reset(); void load(); });
  onMounted(() => { void load(); });
  onBeforeUnmount(() => { generation += 1; });

  return { canManage, items, candidates, loading, busy, error, actionError, notice, load, assign, remove };
}
