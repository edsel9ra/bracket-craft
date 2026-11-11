import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';
import ts from 'typescript';

function vueExpressions(source: string): string {
  const scripts = [...source.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)].map((match) => match[1]!);
  const template = source.match(/<template\b[^>]*>([\s\S]*)<\/template>/)?.[1] ?? '';
  for (const match of template.matchAll(/(?:\bv-[\w:.-]+|[@:][\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g)) scripts.push(match[1] ?? match[2]!);
  for (const match of template.matchAll(/\{\{([\s\S]*?)\}\}/g)) scripts.push(match[1]!);
  return scripts.join('\n;\n');
}

function nativeDialogs(source: string): string[] {
  const filename = 'dialog-check.ts';
  const file = ts.createSourceFile(filename, source, ts.ScriptTarget.Latest, true);
  const host = ts.createCompilerHost({});
  host.getSourceFile = (name) => name === filename ? file : undefined;
  const program = ts.createProgram([filename], { noLib: true, noResolve: true }, host);
  const checker = program.getTypeChecker();
  const found: string[] = [];
  const names = new Set(['confirm', 'alert', 'prompt']);
  function visit(node: ts.Node) {
    if (ts.isCallExpression(node)) {
      const callee = node.expression;
      if (ts.isIdentifier(callee) && names.has(callee.text) && !checker.getSymbolAtLocation(callee)) {
        found.push(callee.text);
      } else if (ts.isPropertyAccessExpression(callee) || ts.isElementAccessExpression(callee)) {
        const name = ts.isPropertyAccessExpression(callee) ? callee.name.text
          : callee.argumentExpression && ts.isStringLiteral(callee.argumentExpression) ? callee.argumentExpression.text : '';
        if (names.has(name) && ['window', 'globalThis', 'self'].includes(callee.expression.getText(file))) found.push(name);
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(file);
  return found;
}

test('native-dialog guard distinguishes native calls from local composables, strings and comments', () => {
  assert.deepEqual(nativeDialogs(''), []);
  assert.deepEqual(nativeDialogs('window.confirm("?"); alert("!"); prompt("?"); window["alert"]("!");'), ['confirm', 'alert', 'prompt', 'alert']);
  assert.deepEqual(nativeDialogs('const { confirm } = useConfirm(); await confirm({}); // alert("!")\nconst text = "window.prompt()";'), []);
  assert.deepEqual(nativeDialogs('globalThis.confirm?.("?"); self.prompt("?");'), ['confirm', 'prompt']);
});

test('native-dialog guard checks Vue directives and interpolations without flagging local confirm', () => {
  assert.deepEqual(nativeDialogs(vueExpressions('<template><button @click="window.confirm(\'x\')">{{ alert("x") }}</button></template>')), ['confirm', 'alert']);
  assert.deepEqual(nativeDialogs(vueExpressions('<script setup>const { confirm } = useConfirm();</script><template><button @click="confirm({})">Confirm</button></template>')), []);
});

test('app contains no native confirm, alert or prompt calls', () => {
  const failures: string[] = [];
  function scan(directory: string) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) scan(path);
      else if (/\.(?:vue|ts|js)$/.test(path)) {
        const source = readFileSync(path, 'utf8');
        const scripts = path.endsWith('.vue') ? vueExpressions(source) : source;
        for (const name of nativeDialogs(scripts)) failures.push(`${path}: ${name}`);
      }
    }
  }
  scan(new URL('../app', import.meta.url).pathname);
  assert.deepEqual(failures, []);
});
