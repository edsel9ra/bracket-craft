import type { PublicAdvance, PublicBracketRound } from './publicBracket.ts';

export interface PublicBracketBox {
  height: number;
  width: number;
  left: number;
  roundTop: number;
}

export interface PublicBracketPath {
  sourceId: string;
  targetId: string;
  d: string;
}

export interface PublicBracketLayout {
  positions: Record<string, { top: number; centerY: number; nominalY: number; collision: boolean }>;
  roundHeights: Record<string, number>;
  paths: PublicBracketPath[];
  width: number;
  height: number;
}

export function layoutPublicBracket(
  rounds: readonly PublicBracketRound[],
  edges: readonly PublicAdvance[],
  boxes: Readonly<Record<string, PublicBracketBox>>,
  gap: number,
): PublicBracketLayout | null {
  if (!Number.isFinite(gap) || gap < 0) return null;
  const matches = rounds.flatMap(round => round.matches);
  for (const match of matches) {
    const box = boxes[match.id];
    if (!box || !Object.values(box).every(Number.isFinite) || box.height <= 0 || box.width <= 0 || box.left < 0 || box.roundTop < 0) return null;
  }
  const baseY = Math.max(0, ...matches.map(match => boxes[match.id]!.roundTop));
  const positions: PublicBracketLayout['positions'] = {};
  let height = baseY;
  for (const round of rounds) {
    let nextTop = baseY;
    for (const match of round.matches) {
      const box = boxes[match.id]!;
      const origins = edges.filter(edge => edge.targetId === match.id).map(edge => positions[edge.sourceId]);
      if (origins.some(origin => !origin)) return null;
      const nominalY = origins.length
        ? origins.reduce((sum, origin) => sum + origin!.centerY, 0) / origins.length
        : nextTop + box.height / 2;
      const centerY = Math.max(nominalY, nextTop + box.height / 2);
      positions[match.id] = { top: centerY - box.height / 2 - box.roundTop, centerY, nominalY, collision: centerY > nominalY };
      nextTop = centerY + box.height / 2 + gap;
      height = Math.max(height, nextTop - gap);
    }
  }
  const paths: PublicBracketPath[] = [];
  for (const edge of edges) {
    const a = boxes[edge.sourceId];
    const b = boxes[edge.targetId];
    const source = positions[edge.sourceId];
    const target = positions[edge.targetId];
    if (!a || !b || !source || !target) return null;
    const right = a.left + a.width;
    const middle = (right + b.left) / 2;
    paths.push({ sourceId: edge.sourceId, targetId: edge.targetId, d: `M ${right} ${source.centerY} H ${middle} V ${target.centerY} H ${b.left}` });
  }
  const roundHeights = Object.fromEntries(rounds.map(round => [round.key, height - (boxes[round.matches[0]!.id]?.roundTop ?? 0)]));
  return { positions, roundHeights, paths, height, width: Math.max(0, ...matches.map(match => boxes[match.id]!.left + boxes[match.id]!.width)) };
}
