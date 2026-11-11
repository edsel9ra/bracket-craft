<script setup lang="ts">


import type { MatchOperationContext } from '~/composables/useMatchOperation';

const props = defineProps<{ context: MatchOperationContext }>();
const { t, statusLabel, realtime, match, isTerminal, matchGameFormat, realtimeStatusLabel, formatDate } = props.context;
const emit = defineEmits<{ retryRealtime: [] }>();
const retryRealtime = () => emit('retryRealtime');
</script>

<template>
<section class="container operation-hero">
      <div class="hero-line">
         <p class="eyebrow">{{ t('match.matchReport') }}</p>
         <span v-if="realtimeStatusLabel" class="realtime-status" :class="`realtime-${realtime.status.value}`" role="status">{{ realtimeStatusLabel }}</span>
         <button v-if="realtime.status.value === 'error'" class="realtime-retry" type="button" @click="retryRealtime">{{ t('common.retry') }}</button>
         <span class="status-pill" :class="{ finished: isTerminal, interrupted: match?.status === 'interrupted' }">{{ statusLabel(match?.status) }}</span>
      </div>
      <div v-if="match" class="match-heading">
        <div>
          <p class="context-line">{{ match.tournament_name }} · {{ match.stage_name }} · {{ t('public.matchday', { value: match.matchday || '-' }) }}</p>
          <h1 class="match-title">
            <TeamCrest
              :team="{ name: match.home_team_name || t('public.toDefine'), short_code: match.home_team_short_code }"
              :crest-url="match.home_team_crest_url"
              :logo-url="match.home_team_logo_url"
              surface="workspace"
            />
            <span>{{ match.home_team_name || t('public.toDefine') }}</span>
            <span class="match-versus">vs</span>
            <TeamCrest
              :team="{ name: match.away_team_name || t('public.toDefine'), short_code: match.away_team_short_code }"
              :crest-url="match.away_team_crest_url"
              :logo-url="match.away_team_logo_url"
              surface="workspace"
            />
            <span>{{ match.away_team_name || t('public.toDefine') }}</span>
          </h1>
          <p class="workspace-copy">{{ formatDate(match.match_date) }}<span v-if="match.group_name"> · {{ match.group_name }}</span></p>
        </div>
        <div class="scoreboard" :aria-label="t('match.result')">
          <strong>{{ match.home_score ?? '—' }}</strong>
          <span>:</span>
          <strong>{{ match.away_score ?? '—' }}</strong>
        </div>
      </div>
      <p v-if="matchGameFormat !== '11v11'" class="muted-note">{{ t('format.context', { format: matchGameFormat }) }}</p>
    </section>
</template>

<style scoped src="./operation.css" />
