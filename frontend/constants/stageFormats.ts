export const STAGE_FORMATS = [
  {
    value: 'round_robin',
    labelKey: 'stage.roundRobin',
    descriptionKey: 'stage.roundRobinDescription',
  },
  {
    value: 'single_elimination',
    labelKey: 'stage.singleElimination',
    descriptionKey: 'stage.singleEliminationDescription',
  },
  {
    value: 'custom_group',
    labelKey: 'stage.customGroup',
    descriptionKey: 'stage.customGroupDescription',
  },
  {
    value: 'swiss',
    labelKey: 'stage.swiss',
    descriptionKey: 'stage.swissDescription',
  },
  {
    value: 'double_elimination',
    labelKey: 'stage.doubleElimination',
    descriptionKey: 'stage.doubleEliminationDescription',
  },
] as const;

export type StageFormat = (typeof STAGE_FORMATS)[number]['value'];

export interface LocalizedStageFormat {
  value: StageFormat;
  label: string;
  description: string;
}

export function getStageFormatOptions(translate: (key: string) => string): LocalizedStageFormat[] {
  return STAGE_FORMATS.map((format) => ({
    value: format.value,
    label: translate(format.labelKey),
    description: translate(format.descriptionKey),
  }));
}
