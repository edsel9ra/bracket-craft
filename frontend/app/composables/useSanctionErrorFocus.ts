export function useSanctionErrorFocus(error: Ref<string>) {
  const target = ref<HTMLElement | null>(null);
  watch(error, async (value) => { if (value) { await nextTick(); target.value?.focus(); } });
  return target;
}
