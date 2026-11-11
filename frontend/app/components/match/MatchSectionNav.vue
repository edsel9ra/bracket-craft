<script setup lang="ts">
import HorizontalScroll from '~/components/ui/HorizontalScroll.vue';

const { t } = useI18n();
const sections = [
  ['seccion-resolucion', 'match.resolutionSection'], ['seccion-campo', 'match.fieldSection'],
  ['seccion-plantillas', 'match.roster'], ['seccion-planilla', 'match.rosterSection'],
  ['seccion-eventos', 'match.events'], ['seccion-cierre', 'match.closingSection'],
] as const;
const current = shallowRef<string>('seccion-resolucion');
let observer: IntersectionObserver | undefined;
let frame = 0;
let updateCurrent = () => {};
function onScroll() {
  cancelAnimationFrame(frame);
  frame = requestAnimationFrame(updateCurrent);
}
onMounted(() => {
  if (typeof IntersectionObserver === 'undefined') return;
  const elements = sections.map(([id]) => document.getElementById(id)).filter((element): element is HTMLElement => Boolean(element));
  const offset = () => {
    const bar = document.querySelector('.match-bar');
    return bar?.getBoundingClientRect().bottom || 0;
  };
  updateCurrent = () => {
    if (window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2) {
      current.value = elements.at(-1)?.id || current.value;
      return;
    }
    const top = offset() + 32;
    const passed = elements.filter((element) => element.getBoundingClientRect().top <= top);
    current.value = passed.at(-1)?.id || elements[0]?.id || current.value;
  };
  observer = new IntersectionObserver(updateCurrent, { threshold: [0, 0.25, 0.5, 0.75, 1] });
  for (const element of elements) observer.observe(element);
  document.addEventListener('scroll', onScroll, { passive: true });
});
onBeforeUnmount(() => {
  observer?.disconnect();
  document.removeEventListener('scroll', onScroll);
  cancelAnimationFrame(frame);
});
</script>

<template>
  <nav class="container match-section-nav" :aria-label="t('match.sectionNavigation')">
    <HorizontalScroll :label="t('match.sectionNavigation')">
      <div class="section-links">
        <a v-for="[id, label] in sections" :key="id" :href="`#${id}`" :aria-current="current === id ? 'location' : undefined">{{ t(label) }}</a>
      </div>
    </HorizontalScroll>
  </nav>
</template>

<style scoped>
.match-section-nav { padding-block: var(--space-3); }
.section-links { display: flex; gap: var(--space-1); }
a { flex: 0 0 auto; padding: var(--space-2) var(--space-3); border-bottom: 2px solid transparent; color: var(--color-muted); font-size: var(--text-sm); text-decoration: none; }
a[aria-current="location"] { border-color: var(--color-accent); color: var(--color-accent); }
a:focus-visible { outline: 2px solid var(--color-accent); outline-offset: -2px; }
</style>
