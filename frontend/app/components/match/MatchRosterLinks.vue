<script setup lang="ts">


import type { MatchOperationContext } from '~/composables/useMatchOperation';

const props = defineProps<{ context: MatchOperationContext }>();
const { t, teamRosters, teamRosterLink } = props.context;
</script>

<template>
<section class="panel" id="seccion-plantillas" tabindex="-1">
            <div class="panel-heading"><div><p class="eyebrow">02 · {{ t('match.roster') }}</p><h2>{{ t('match.roster') }}</h2></div></div>
            <p class="muted-note">{{ t('match.rosterManagedInRosters') }}</p>
            <ul class="roster-links">
              <li v-for="team in teamRosters" :key="`roster-link-${team.key}`">
                <NuxtLink v-if="team.team_id" :to="teamRosterLink(team.team_id)">{{ t('match.openTeamRoster', { team: team.name }) }}</NuxtLink>
              </li>
            </ul>
          </section>
</template>

<style scoped src="./operation.css" />
