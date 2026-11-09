import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import test from 'node:test';

const app = new URL('../app/', import.meta.url);
const uiNames = readdirSync(new URL('components/ui/', app))
  .filter((file) => file.endsWith('.vue'))
  .map((file) => file.slice(0, -4));

function missingImports(source: string, names: string[]): string[] {
  const template = source.match(/<template>[\s\S]*<\/template>/)?.[0] ?? '';
  const script = source.match(/<script\b[^>]*>([\s\S]*?)<\/script>/)?.[1] ?? '';
  return names.filter((name) => {
    const used = new RegExp(`<${name}(?=[\\s/>])`).test(template);
    const imported = new RegExp(`import\\s+${name}\\s+from\\s+['"][^'"]*[/]${name}\\.vue['"]`).test(script);
    return used && !imported;
  });
}

test('acepta componentes UI importados explícitamente', () => {
  assert.deepEqual(missingImports(`<template><FieldError /></template>
    <script setup>import FieldError from './FieldError.vue';</script>`, ['FieldError']), []);
});

test('no exige imports para una plantilla vacía ni para nombres con prefijo Ui', () => {
  assert.deepEqual(missingImports('', ['FieldError']), []);
  assert.deepEqual(missingImports('<template><UiFieldError /></template>', ['FieldError']), []);
});

test('detecta el componente sin import y no acepta imports de otro componente', () => {
  assert.deepEqual(missingImports('<template><FieldError /></template>', ['FieldError']), ['FieldError']);
  assert.deepEqual(missingImports(`<template><FieldError /></template>
    <script setup>import FieldError from './FormField.vue';</script>`, ['FieldError']), ['FieldError']);
});

test('todos los componentes UI usados sin prefijo tienen import explícito', () => {
  const files = readdirSync(app, { recursive: true }).filter((file) => file.endsWith('.vue'));
  assert.ok(files.length > 0);
  assert.ok(uiNames.includes('FieldError'));
  for (const file of files) {
    const missing = missingImports(readFileSync(new URL(file, app), 'utf8'), uiNames);
    assert.deepEqual(missing, [], `${file}: componentes UI sin import explícito: ${missing.join(', ')}`);
  }
});
