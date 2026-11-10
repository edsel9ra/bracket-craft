import assert from 'node:assert/strict';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import test from 'node:test';
import ts from 'typescript';
import { parse } from 'vue/compiler-sfc';

const app = new URL('../app/', import.meta.url);
const declarations = new URL('../.nuxt/components.d.ts', import.meta.url);
assert.ok(existsSync(declarations), 'Run pnpm exec nuxt prepare before the component audit (as lint does in CI).');
const autoImports = new Set(
  [...readFileSync(declarations, 'utf8').matchAll(/^export const (\w+):/gm)].map((match) => match[1]!),
);
// Vue built-ins and Vue Router globals registered by Nuxt; Nuxt components come from its generated declarations.
const globals = new Set(['Transition', 'TransitionGroup', 'KeepAlive', 'Teleport', 'Suspense', 'RouterLink', 'RouterView']);

function bindingNames(name: ts.BindingName): string[] {
  return ts.isIdentifier(name)
    ? [name.text]
    : name.elements.flatMap((element) => ts.isOmittedExpression(element) ? [] : bindingNames(element.name));
}

function localComponents(source: string, setup: boolean): Set<string> {
  const file = ts.createSourceFile('component.ts', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  const names = new Set<string>();
  for (const statement of file.statements) {
    if (setup && ts.isImportDeclaration(statement) && statement.importClause && !statement.importClause.isTypeOnly) {
      const clause = statement.importClause;
      if (clause.name) names.add(clause.name.text);
      if (clause.namedBindings) {
        if (ts.isNamespaceImport(clause.namedBindings)) names.add(clause.namedBindings.name.text);
        else for (const element of clause.namedBindings.elements) {
          if (!element.isTypeOnly) names.add(element.name.text);
        }
      }
    }
    const declared = ts.canHaveModifiers(statement) && ts.getModifiers(statement)?.some((modifier) => modifier.kind === ts.SyntaxKind.DeclareKeyword);
    if (setup && !declared) {
      if (ts.isVariableStatement(statement)) {
        for (const declaration of statement.declarationList.declarations) {
          for (const name of bindingNames(declaration.name)) names.add(name);
        }
      } else if ((ts.isFunctionDeclaration(statement) || ts.isClassDeclaration(statement)) && statement.name) {
        names.add(statement.name.text);
      }
    }
    if (!ts.isExportAssignment(statement)) continue;
    let options = statement.expression;
    if (ts.isCallExpression(options) && options.arguments[0]) options = options.arguments[0];
    if (!ts.isObjectLiteralExpression(options)) continue;
    for (const property of options.properties) {
      if (!ts.isPropertyAssignment(property) || property.name.getText(file) !== 'components'
        || !ts.isObjectLiteralExpression(property.initializer)) continue;
      for (const component of property.initializer.properties) {
        if (component.name && (ts.isIdentifier(component.name) || ts.isStringLiteral(component.name))) {
          names.add(component.name.text);
        }
      }
    }
  }
  return names;
}

function missingComponents(source: string, available: Set<string> = autoImports): string[] {
  const { descriptor, errors } = parse(source);
  assert.deepEqual(errors, [], 'the SFC must parse before auditing its components');
  const local = new Set([
    ...localComponents(descriptor.scriptSetup?.content ?? '', true),
    ...localComponents(descriptor.script?.content ?? '', false),
  ]);
  const tags = new Set<string>();
  function visit(node: { tag?: string; children?: unknown[] }) {
    if (node.tag && /^[A-Z]/.test(node.tag)) tags.add(node.tag);
    for (const child of node.children ?? []) visit(child as Parameters<typeof visit>[0]);
  }
  if (descriptor.template?.ast) visit(descriptor.template.ast);
  return [...tags].filter((tag) => !local.has(tag.split('.')[0]!) && !available.has(tag) && !globals.has(tag)).sort();
}

test('resolves runtime imports, aliases, namespaces and local setup components', () => {
  assert.deepEqual(missingComponents(`<script setup lang="ts">
    import Pitch from './TeamPitch.vue';
    import { Thing as Alias } from './library';
    import * as Fields from './fields';
    const AsyncPitch = defineAsyncComponent(() => import('./TeamPitch.vue'));
  </script><template><Pitch/><Alias/><Fields.Input/><AsyncPitch/></template>`), []);
});

test('accepts Nuxt directory prefixes, lazy components and framework globals', () => {
  assert.ok(autoImports.has('PublicTeamPitch'));
  assert.ok(autoImports.has('LazyPublicTeamPitch'));
  assert.deepEqual(missingComponents('<template><PublicTeamPitch/><LazyPublicTeamPitch/><NuxtLink/><ClientOnly/><Transition/><Teleport/></template>'), []);
  assert.deepEqual(missingComponents('<template><TeamPitch/></template>'), ['TeamPitch']);
});

test('does not count type-only imports, comments, attributes or nested script bindings', () => {
  assert.deepEqual(missingComponents(`<script setup lang="ts">
    import type TypeOnly from './types';
    import { type NamedType } from './types';
    function make() { const Hidden = {}; }
  </script><template><!-- <Ignored/> --><div title="<AlsoIgnored>"/><TypeOnly/><NamedType/><Hidden/></template>`), ['Hidden', 'NamedType', 'TypeOnly']);
});

test('accepts explicit Options API registration but not unregistered imports', () => {
  assert.deepEqual(missingComponents(`<script>import Pitch from './Pitch.vue';
    export default defineComponent({ components: { Registered: Pitch } });
    </script><template><Registered/><Pitch/></template>`), ['Pitch']);
  assert.deepEqual(missingComponents('<script setup>const value = 1;</script>'), []);
  assert.throws(() => missingComponents('<template><Broken></template>'), /the SFC must parse/);
  assert.deepEqual(missingComponents('<template><Unknown/></template>'), ['Unknown']);
});

test('all PascalCase template tags in frontend/app resolve locally, through Nuxt or as globals', () => {
  const files = readdirSync(app, { recursive: true }).filter((file) => file.endsWith('.vue'));
  assert.ok(files.length > 0);
  const missing = files.flatMap((file) => missingComponents(readFileSync(new URL(file, app), 'utf8'))
    .map((tag) => `${file}: ${tag}`));
  assert.deepEqual(missing, [], 'Unresolved template components');
});

test('PublicLineupModal explicitly imports and renders its TeamPitch with the selected team', () => {
  const modal = readFileSync(new URL('components/public/PublicLineupModal.vue', app), 'utf8');
  assert.match(modal, /import TeamPitch from ['"](?:~\/components\/public\/|\.\/)TeamPitch\.vue['"]/);
  assert.match(modal, /<TeamPitch\s+:team="team"\s*\/>/);
});
