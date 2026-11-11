<script setup lang="ts">
import ThemeSwitcher from '~/components/ThemeSwitcher.vue';
import { placeFloatingTheme } from '~/utils/floatingPreferences';

const group = useTemplateRef<HTMLDivElement>('group');
const placement = shallowRef<{ direction: 'row' | 'column'; height: number } | null>(null);
let cleanup = () => {};

onMounted(() => {
  const root = group.value!;
  const language = root.querySelector<HTMLElement>('.language-switcher')!;
  const theme = root.querySelector<HTMLElement>('.theme-switcher')!;
  let frame = 0;
  function update() {
    frame = 0;
    const viewport = { width: document.documentElement.clientWidth, height: window.innerHeight };
    const obstacles: DOMRect[] = [];
    function add(rect: DOMRect) {
      if (rect.width > 1 && rect.height > 1 && rect.bottom > 0 && rect.y < viewport.height) obstacles.push(rect);
    }
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node: Node | null;
    while ((node = walker.nextNode())) {
      const parent = node.parentElement;
      if (!node.textContent?.trim() || !parent || root.contains(parent) || parent.closest('script,style,.visually-hidden,#nuxt-devtools-container,#nuxt-devtools-anchor')) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      for (const rect of range.getClientRects()) add(rect);
    }
    for (const element of document.querySelectorAll<HTMLElement>('a,button,input,select,textarea,[role="button"]')) {
      if (!root.contains(element) && !element.closest('#nuxt-devtools-container,#nuxt-devtools-anchor,.visually-hidden')) add(element.getBoundingClientRect());
    }
    const lang = language.getBoundingClientRect();
    const size = theme.getBoundingClientRect();
    const margin = Number.parseFloat(getComputedStyle(root).right);
    if (!root.isConnected || !lang.width || !lang.height || !size.width || !size.height || !Number.isFinite(margin)) return;
    const next = placeFloatingTheme(lang, size, viewport, obstacles, margin, window.matchMedia('(min-width: 1280px)').matches);
    placement.value = next ? { direction: next.direction, height: lang.height + size.height + next.gap } : null;
  }
  function schedule() {
    if (!frame) frame = requestAnimationFrame(update);
  }
  const resize = new ResizeObserver(schedule);
  for (const element of [document.body, language, theme]) resize.observe(element);
  const mutation = new MutationObserver(records => {
    if (records.some(record => !root.contains(record.target))) schedule();
  });
  mutation.observe(document.body, { childList: true, characterData: true, subtree: true });
  window.addEventListener('resize', schedule);
  window.addEventListener('scroll', schedule, { capture: true, passive: true });
  const layoutEvents = ['animationend', 'animationcancel', 'transitionend', 'transitioncancel', 'pointerover', 'pointerout'];
  for (const event of layoutEvents) window.addEventListener(event, schedule, true);
  void document.fonts.ready.then(schedule);
  update();
  cleanup = () => {
    resize.disconnect();
    mutation.disconnect();
    window.removeEventListener('resize', schedule);
    window.removeEventListener('scroll', schedule, true);
    for (const event of layoutEvents) window.removeEventListener(event, schedule, true);
    cancelAnimationFrame(frame);
  };
});
onBeforeUnmount(() => cleanup());
</script>

<template>
  <div ref="group" class="public-preferences" :class="{ 'is-ready': placement, 'is-stacked': placement?.direction === 'column' }" :style="{ height: placement?.direction === 'column' ? `${placement.height}px` : undefined }">
    <ThemeSwitcher />
    <LanguageSwitcher />
  </div>
</template>

<style scoped>
.public-preferences { position: fixed; right: 20px; bottom: 20px; z-index: 30; display: flex; flex-wrap: wrap-reverse; align-items: end; justify-content: space-between; gap: var(--space-2); max-width: calc(100vw - 40px); }
.public-preferences.is-stacked { flex-direction: column; flex-wrap: nowrap; align-items: end; }
.public-preferences:not(.is-ready) :deep(.theme-switcher) { visibility: hidden; }
.public-preferences :deep(.language-switcher) { position: static; flex: 0 0 auto; }
@media (max-width: 480px) { .public-preferences { right: 12px; bottom: 12px; max-width: calc(100vw - 24px); } }
@media (min-width: 480px) and (max-width: 1280px) {
  .public-preferences :deep(.theme-switcher) { padding: 0 var(--space-2); }
}
@media (min-width: 1280px) {
  .public-preferences { align-items: center; }
  .public-preferences :deep(.theme-switcher) { padding: var(--space-1) var(--space-2); }
}
</style>
