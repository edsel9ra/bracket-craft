import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { nextTabIndex } from '../app/utils/tabs.ts';

const source = (name: string) => readFileSync(new URL(`../app/components/ui/${name}.vue`, import.meta.url), 'utf8');

test('Button has closed variants and blocks busy or disabled clicks including links', () => {
  const button = source('Button');
  assert.match(button, /'primary' \| 'secondary' \| 'danger' \| 'ghost'/);
  assert.match(button, /:aria-busy="busy/);
  assert.match(button, /props.busy \|\| props.disabled/);
  assert.match(button, /event.preventDefault\(\)/);
  assert.match(button, /event.stopImmediatePropagation\(\)/);
  assert.match(button, /'button' \| 'NuxtLink'/);
});

test('Surface, StatusPill and StateMessage expose bounded semantics', () => {
  assert.match(source('Surface'), /level\?: 1 \| 2 \| 3/);
  assert.match(source('StatusPill'), /'neutral' \| 'success' \| 'warning' \| 'danger' \| 'live'/);
  assert.match(source('StatusPill'), /default\(\):/);
  assert.match(source('StateMessage'), /kind === 'error' \? 'alert' : 'status'/);
  assert.match(source('StateMessage'), /emit\('retry'\)/);
  assert.doesNotMatch(source('StateMessage'), /aria-busy/);
});

test('Tabs implement roving focus and connected panels', () => {
  const tabs = source('Tabs');
  for (const role of ['tablist', 'tab', 'tabpanel']) assert.match(tabs, new RegExp(`role="${role}"`));
  assert.match(tabs, /:aria-controls=/);
  assert.match(tabs, /:aria-labelledby=/);
  assert.match(tabs, /:tabindex="model === tab.id \? 0 : -1"/);
  assert.match(tabs, /defineModel<string>/);
  assert.equal(nextTabIndex('ArrowRight', 2, 3), 0);
  assert.equal(nextTabIndex('ArrowLeft', 0, 3), 2);
  assert.equal(nextTabIndex('Home', 2, 3), 0);
  assert.equal(nextTabIndex('End', 0, 3), 2);
  assert.equal(nextTabIndex('Tab', 1, 3), null);
  assert.equal(nextTabIndex('ArrowRight', 0, 0), null);
});

test('DataTable keeps a caption, scoped headers and the accessible scroller', () => {
  const table = source('DataTable');
  assert.match(table, /<HorizontalScroll :label="caption"/);
  assert.match(table, /<caption[^>]*>\{\{ caption \}\}/);
  assert.match(table, /scope="col"/);
  assert.match(table, /:scope="column.rowHeader \? 'row' : undefined"/);
});
