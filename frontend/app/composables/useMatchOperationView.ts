import type { MatchOperationContext } from '~/composables/useMatchOperation';
import { primaryAction, type MatchPrimaryAction } from '~/utils/matchPrimaryAction';

export function useMatchOperationView(context: MatchOperationContext) {
  const snapshot = computed(() => JSON.stringify([context.lineupRoles.value, context.lineupPositions.value, context.lineupFormations.value]));
  const savedLineup = shallowRef<string | null>(null);
  watch([context.operation, context.selectedSegmentId], () => { savedLineup.value = snapshot.value; }, { flush: 'post' });
  const action = computed(() => primaryAction({
    status: context.match.value?.status || '', canOperate: context.canOperateMatch.value,
    canManage: context.canManageTournaments.value, activeSegment: Boolean(context.activeSegment.value),
    lineupDirty: savedLineup.value !== null && savedLineup.value !== snapshot.value,
    draftEvents: context.draftEvents.value.length, closeReady: context.closeValidationIssue() === null,
    isTerminal: context.isTerminal.value,
  }));
  const actionDisabled = computed(() => Boolean(context.busyAction.value) || context.isTerminal.value
    || (action.value?.id === 'saveLineup' && !context.selectedSegmentIsActive.value));

  function activateAction(next: MatchPrimaryAction) {
    if (actionDisabled.value || !context.canOperateMatch.value) return;
    if (next.mode === 'run') { void context.saveLineup(); return; }
    const section = document.querySelector<HTMLElement>(next.target);
    if (!section) return;
    const control = section.querySelector<HTMLElement>('input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), a[href]') || section;
    control.focus({ preventScroll: true });
    section.scrollIntoView({ block: 'start', behavior: 'auto' });
  }

  let observer: ResizeObserver | undefined;
  const previous = new Map<string, string>();
  onMounted(() => {
    const root = document.documentElement;
    const keys = ['--operation-sticky-top', '--operation-bar-height', '--operation-action-height'];
    for (const key of keys) previous.set(key, root.style.getPropertyValue(key));
    function observeLayout() {
      observer?.disconnect();
      const elements = ['.workspace-topbar', '.workspace-context', '.match-bar', '.match-action-bar'].map((selector) => document.querySelector<HTMLElement>(selector));
      const update = () => {
        root.style.setProperty(keys[0]!, `${(elements[0]?.offsetHeight || 0) + (elements[1]?.offsetHeight || 0)}px`);
        root.style.setProperty(keys[1]!, `${elements[2]?.offsetHeight || 0}px`);
        if (elements[3]?.offsetHeight) root.style.setProperty(keys[2]!, `${elements[3].offsetHeight}px`);
      };
      update();
      if (typeof ResizeObserver !== 'undefined') {
        observer = new ResizeObserver(update);
        for (const element of elements) if (element) observer.observe(element);
      }
    }
    observeLayout();
    watch(() => Boolean(context.operation.value), observeLayout, { flush: 'post' });
  });
  onBeforeUnmount(() => {
    observer?.disconnect();
    for (const [key, value] of previous) {
      if (value) document.documentElement.style.setProperty(key, value);
      else document.documentElement.style.removeProperty(key);
    }
  });
  return { action, actionDisabled, activateAction };
}
