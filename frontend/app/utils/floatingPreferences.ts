interface Size { width: number; height: number }
interface Rect extends Size { x: number; y: number }

export function placeFloatingTheme(language: Rect, theme: Size, viewport: Size, obstacles: readonly Rect[], margin: number, centered = false): { direction: 'row' | 'column'; gap: number } | null {
  if (![language.width, language.height, theme.width, theme.height, viewport.width, viewport.height].every(value => Number.isFinite(value) && value > 0)
    || ![language.x, language.y, margin].every(Number.isFinite) || margin < 0) throw new RangeError('Invalid preference geometry');
  function fits(rect: Rect) {
    return rect.x >= margin && rect.y >= margin
      && rect.x + rect.width <= viewport.width - margin && rect.y + rect.height <= viewport.height - margin
      && !obstacles.some(other => rect.x < other.x + other.width && rect.x + rect.width > other.x && rect.y < other.y + other.height && rect.y + rect.height > other.y);
  }
  const size = { width: theme.width, height: theme.height };
  const rowY = language.y + (language.height - theme.height) * (centered ? 0.5 : 1);
  if (fits({ ...size, x: language.x - 8 - theme.width, y: rowY })) return { direction: 'row', gap: 8 };
  for (let gap = 8; language.y - gap - theme.height >= margin; gap += 4) {
    if (fits({ ...size, x: language.x + language.width - theme.width, y: language.y - gap - theme.height })) return { direction: 'column', gap };
  }
  return null;
}
