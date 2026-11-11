<script setup lang="ts">
import { MAXIMUM_SOURCE_LABEL_KEYS } from '~/utils/matchResolution';

import type { MatchOperationContext } from '~/composables/useMatchOperation';

const props = defineProps<{ context: MatchOperationContext }>();
const { t, isTerminal, canOperateMatch, resolutionFallback, resolutionChangeNotice, resolutionOptions, resolutionLimits, resolutionMaximumSource, selectedResolution } = props.context;
const emit = defineEmits<{
  onResolutionChange: [event: Event];
}>();
const onResolutionChange = (event: Event) => emit('onResolutionChange', event);
</script>

<template>
<section class="panel panel-wide resolution-panel" id="seccion-resolucion" tabindex="-1" aria-labelledby="planned-resolution-heading">
          <div class="panel-heading">
            <div><p class="eyebrow">{{ t('match.plannedResolution') }}</p><h2 id="planned-resolution-heading">{{ t('match.resolution') }}</h2></div>
            <span class="muted-note">{{ t('match.plannedResolutionHint') }}</span>
          </div>
          <div class="resolution-summary">
            <label class="field">{{ t('match.plannedResolution') }}
              <select :value="selectedResolution" :disabled="!canOperateMatch || isTerminal" @change="onResolutionChange">
                <option v-for="option in resolutionOptions" :key="option.value" :value="option.value">{{ t(option.labelKey) }}</option>
              </select>
            </label>
            <p class="resolution-limits" role="status">
              <strong>{{ t('match.resolutionMaximum', { max: resolutionLimits.maxMinute }) }}</strong>
              <span>{{ t('match.resolutionAddedMaximum', { max: resolutionLimits.addedMax }) }}</span>
              <span>{{ t(MAXIMUM_SOURCE_LABEL_KEYS[resolutionMaximumSource]) }}</span>
            </p>
            <p v-if="resolutionFallback" class="segment-warning" role="status">{{ t('match.resolutionFallenBack') }}</p>
            <p v-if="resolutionChangeNotice" class="segment-warning" role="status">{{ t(resolutionChangeNotice.key, resolutionChangeNotice.params) }}</p>
          </div>
        </section>
</template>

<style scoped src="./operation.css" />
