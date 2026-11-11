export function checklistPresentation(valid: boolean, terminal: boolean, missingKey?: string) {
  const neutral = !valid && terminal && Boolean(missingKey);
  return {
    valid,
    neutral,
    icon: valid ? '✓' : neutral ? '—' : '!',
    statusKey: valid ? 'common.ready' : neutral ? missingKey! : 'common.incomplete',
  };
}
