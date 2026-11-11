import type { ResolutionType } from './matchResolution.ts';

export interface PrimaryActionInput {
  status: string;
  resolution: ResolutionType;
  canOperate: boolean;
  canManage: boolean;
  activeSegment: boolean;
  lineupDirty: boolean;
  draftEvents: number;
  closeReady: boolean;
  isTerminal: boolean;
}

export function primaryAction(input: PrimaryActionInput) {
  if (input.isTerminal || !input.canOperate) return null;
  if (!input.activeSegment && input.resolution === 'walkover' && ['scheduled', 'live', 'interrupted'].includes(input.status)) {
    return { id: 'closeReport', labelKey: 'match.reviewClosing', mode: 'focus', target: '#seccion-cierre' } as const;
  }
  if (!input.activeSegment && ['scheduled', 'interrupted', 'suspended'].includes(input.status)) {
    return { id: 'startSegment', labelKey: 'match.startNextSegment', mode: 'focus', target: '#seccion-campo' } as const;
  }
  if (input.lineupDirty) {
    return { id: 'saveLineup', labelKey: 'match.saveLineup', mode: 'run', target: '#seccion-planilla' } as const;
  }
  if (input.draftEvents > 0 || input.closeReady) {
    return { id: 'closeReport', labelKey: 'match.reviewClosing', mode: 'focus', target: '#seccion-cierre' } as const;
  }
  return { id: 'addEvent', labelKey: 'match.addEvent', mode: 'focus', target: '#seccion-eventos' } as const;
}

export type MatchPrimaryAction = NonNullable<ReturnType<typeof primaryAction>>;
