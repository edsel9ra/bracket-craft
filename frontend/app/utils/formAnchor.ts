export function focusFormAnchor(event: MouseEvent): void {
  if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  const anchor = event.currentTarget as HTMLAnchorElement | null;
  if (!anchor?.hash) return;
  const form = document.getElementById(anchor.hash.slice(1));
  const field = form?.querySelector<HTMLElement>('input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled])');
  if (field) requestAnimationFrame(() => field.focus({ preventScroll: true }));
}
