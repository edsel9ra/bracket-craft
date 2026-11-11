import { onBeforeUnmount, onMounted, shallowRef, watch, type Ref } from 'vue';
import type { PublicAdvance, PublicBracketRound } from '~/utils/publicBracket';
import { layoutPublicBracket, type PublicBracketBox, type PublicBracketLayout } from '~/utils/publicBracketLayout';
import { SPACING } from '~/utils/designTokens';

export function usePublicBracketLayout(rounds: Ref<PublicBracketRound[]>, edges: Ref<PublicAdvance[]>) {
  const container = shallowRef<HTMLElement | null>(null);
  const layout = shallowRef<PublicBracketLayout | null>(null);
  let observer: ResizeObserver | undefined;
  let frame = 0;
  let mounted = false;

  function measure() {
    frame = 0;
    const root = container.value;
    if (!root) return;
    const rect = root.getBoundingClientRect();
    const boxes: Record<string, PublicBracketBox> = {};
    for (const card of root.querySelectorAll<HTMLElement>('.bracket-match')) {
      const id = card.dataset.matchId;
      const list = card.parentElement;
      if (!id || !list) continue;
      const box = card.getBoundingClientRect();
      boxes[id] = { width: box.width, height: box.height, left: box.left - rect.left, roundTop: list.getBoundingClientRect().top - rect.top };
    }
    const next = layoutPublicBracket(rounds.value, edges.value, boxes, SPACING[7]);
    if (JSON.stringify(next) !== JSON.stringify(layout.value)) layout.value = next;
  }

  function schedule() {
    if (mounted && !frame) frame = requestAnimationFrame(measure);
  }

  function connect() {
    if (!mounted) return;
    observer?.disconnect();
    layout.value = null;
    const root = container.value;
    if (!root) return;
    observer = new ResizeObserver(schedule);
    observer.observe(root);
    for (const card of root.querySelectorAll('.bracket-match')) observer.observe(card);
    schedule();
  }

  watch([container, rounds, edges], connect, { flush: 'post' });
  onMounted(() => {
    mounted = true;
    connect();
    void document.fonts.ready.then(schedule);
  });
  onBeforeUnmount(() => {
    mounted = false;
    observer?.disconnect();
    cancelAnimationFrame(frame);
  });
  return { container, layout };
}
