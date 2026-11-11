import assert from 'node:assert/strict';
import { readdirSync, readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';
import { BREAKPOINTS, CSS_TOKENS, RADII, SPACING, TEXT_SIZES } from '../app/utils/designTokens.ts';

const ROOT = new URL('../app/', import.meta.url).pathname;

export const PENDING_MIGRATION = [
  ['pages/workspace/matches/[id].vue', 'opción 3: operación'],
  ['components/RulesEditor.vue', 'opción 3: editor de reglas'],
  ['components/rules/', 'opción 3: asistentes de reglas'],
  ['components/TeamsWizard.vue', 'opción 3: asistente de equipos'],
  ['components/StageTeamsWizard.vue', 'opción 3: asistente de fases'],
  ['components/wizard/', 'opción 3: infraestructura de asistentes'],
  ['pages/workspace/index.vue', 'T9'],
  ['pages/workspace/tournaments/[id]/index.vue', 'T9'],
  ['pages/workspace/tournaments/[id]/calendar.vue', 'T9'],
  ['pages/workspace/tournaments/[id]/rosters.vue', 'T9'],
  ['components/WorkspaceShell.vue', 'T9'],
  ['components/FormatWarning.vue', 'T9'],
  ['assets/css/main.css', 'T9: estilos globales compartidos con pantallas privadas'],
] as const;

export const DESIGN_EXCEPTIONS: { file: string; property: string; value: string; reason: string }[] = [
  { file: 'pages/login.vue', property: 'font-size', value: 'clamp(2.4rem, 8vw, 4.6rem)', reason: 'VI-1: display aumenta el titular de acceso un 37% en escritorio y altera los saltos de línea del formulario.' },
  { file: 'pages/invitations/[token].vue', property: 'font-size', value: 'clamp(2.5rem, 8vw, 4.8rem)', reason: 'VI-1: mantener la composición del titular de invitación dentro de su tarjeta.' },
  { file: 'pages/admin/index.vue', property: 'font-size', value: '2.5rem', reason: 'Cifras de métricas de ancho limitado: display fluido no cabe en las tarjetas.' },
  { file: 'pages/admin/index.vue', property: 'padding', value: '4vh 0 4vh', reason: 'Ritmo del hero de administración proporcional a la ventana.' },
  { file: 'pages/workspace/members.vue', property: 'padding', value: '5vh 0 4vh', reason: 'Ritmo del hero de miembros proporcional a la ventana.' },
  ...['0.62rem', '0.53rem', '0.58rem', '0.63rem', '0.54rem'].map((value) => ({ file: 'components/public/MatchPitch.vue', property: 'font-size', value, reason: 'Etiquetas dentro de la geometría del campo, con nombre completo accesible.' })),
  ...['clamp(0.62rem, 2cqw, 1.1rem)', '0.62rem', '0.6rem', '0.52rem', '0.58rem', '0.63rem', '0.54rem', '0.48rem'].map((value) => ({ file: 'components/public/TeamPitch.vue', property: 'font-size', value, reason: 'Etiquetas del campo adaptadas al contenedor; nombres completos en alternativa textual.' })),
  ...['MatchPitch', 'TeamPitch'].map((component) => ({ file: `components/public/${component}.vue`, property: 'gap', value: '1px', reason: 'Separación entre avatar, dorsal y etiqueta sin desplazar los slots tácticos.' })),
  { file: 'components/public/PublicLineupModal.vue', property: 'font-size', value: '0.62em', reason: 'Separador proporcional entre nombres de equipos, no tamaño de lectura independiente.' },
  { file: 'pages/index.vue', property: 'font-size', value: '4rem', reason: 'Cifra del marcador ilustrado; display desborda la tarjeta y xl pierde jerarquía.' },
  { file: 'pages/index.vue', property: 'font-size', value: 'clamp(3rem, 15vw, 5.5rem)', reason: 'VI-1: display reduce el titular móvil un 32% y cambia su composición de tres líneas.' },
  { file: 'pages/tournaments/[id].vue', property: 'font-size', value: 'clamp(3.4rem, 10vw, 8.5rem)', reason: 'VI-1: display reduce el titular un 26% y altera su salto de línea y jerarquía.' },
  { file: 'pages/index.vue', property: 'gap', value: '8vw', reason: 'Composición proporcional entre las dos columnas del hero.' },
  { file: 'pages/index.vue', property: 'padding', value: '10vh 0 14vh', reason: 'Ritmo vertical de la portada proporcional a la altura de la ventana.' },
  { file: 'pages/index.vue', property: 'padding-top', value: '8vh', reason: 'Ritmo vertical del hero móvil.' },
  { file: 'pages/tournaments/[id].vue', property: 'padding', value: '10vh 0 8vh', reason: 'Composición del hero de torneo proporcional a la ventana.' },
  { file: 'pages/tournaments/[id].vue', property: 'padding-top', value: '8vh', reason: 'Ritmo vertical del hero móvil.' },
];

// Se vigilan tamaños, espaciado, radios, colores y media queries, no geometría
// (width/height/inset), trazos ni tiempos. 0, auto, inherit, porcentajes y palabras
// clave CSS no fijan pasos. rem se convierte a px con raíz de 16; em/cqw/vh/vw
// no se aceptan salvo excepción o la escala fluida exacta. Los bordes de 1px
// no se inspeccionan como espaciado. Un literal del paso exacto es válido;
// la migración usa var(). Colores literales solo en tokens.css, con espejo TS.
type Violation = { property: string; value: string };
const pixels = (value: string) => Number.parseFloat(value) * (value.endsWith('rem') ? 16 : 1);
const textSteps = Object.values(TEXT_SIZES).filter((value) => !value.startsWith('clamp')).map(pixels);

function inspect(source: string, file: string): Violation[] {
  const clean = source.replace(/\/\*[\s\S]*?\*\//g, '');
  const css = file.endsWith('.css') ? clean : [...clean.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/g)].map((match) => match[1]).join('\n');
  const inline = [...clean.matchAll(/\bstyle="([^"]*)"/g)].map((match) => match[1]).join(';');
  const found: Violation[] = [];
  function add(property: string, value: string) {
    if (!DESIGN_EXCEPTIONS.some((entry) => entry.file === file && entry.property === property && entry.value === value)) found.push({ property, value });
  }
  const objects = [...clean.matchAll(/\b(fontSize|borderRadius|rowGap|columnGap|gap|(?:padding|margin)(?:Top|Right|Bottom|Left|Inline(?:Start|End)?|Block(?:Start|End)?)?)\s*:\s*(['"])([^'"]+)\2/g)].map((match) => `${match[1]!.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)}: ${match[3]}`).join(';');
  const declarations = `${css};${inline};${objects}`;
  for (const match of declarations.matchAll(/(?:^|[;{])\s*(font-size|border(?:-(?:top|bottom|start|end)-(?:left|right|start|end))?-radius|(?:row-|column-)?gap|(?:padding|margin)(?:-(?:top|right|bottom|left|inline(?:-start|-end)?|block(?:-start|-end)?))?)\s*:\s*([^;{}]+)/gm)) {
    const property = match[1]!;
    const value = match[2]!.trim().replace(/\s*!important$/, '');
    if (property === 'font-size' && Object.values(TEXT_SIZES).includes(value as typeof TEXT_SIZES[keyof typeof TEXT_SIZES])) continue;
    const scale = property === 'font-size' ? textSteps : property.includes('radius') ? Object.values(RADII) : Object.values(SPACING);
    const dimensions = [...value.matchAll(/(-?\d*\.?\d+)(rem|px|em|cqw|vw|vh|vmin|vmax|dvh|pt|ch|ex|lh|svh|lvh|%)\b/g)];
    if (dimensions.some((dimension) => dimension[2] !== '%' && Number(dimension[1]) !== 0 && (!['px', 'rem'].includes(dimension[2]!) || !scale.includes(pixels(dimension[0]) as never)))) add(property, value);
  }
  for (const query of css.matchAll(/@media[^{}]+/g)) {
    for (const match of query[0].matchAll(/\d*\.?\d+(?:px|rem|em)\b/g)) {
      const value = match[0];
      if (!Object.values(BREAKPOINTS).includes(pixels(value) as never)) add('@media', value);
    }
  }
  for (const match of clean.matchAll(/#[\da-f]{3,8}\b|rgba?\([^()]*\)/gi)) {
    const value = match[0];
    if (file === 'assets/css/tokens.css' && Object.values(CSS_TOKENS).includes(value)) continue;
    add('color', value);
  }
  return found;
}

test('scale guard detects invalid values and accepts canonical steps, tokens and geometry', () => {
  assert.deepEqual(inspect('.x { padding: 0 auto; margin: 10%; gap: var(--space-3); border: 1px solid transparent; width: 37px; font-size: 0.875rem; }', 'fixture.css'), []);
  assert.deepEqual(inspect('.x { padding: 7px; margin-inline: 3px; gap: 9px; font-size: 17px; border-radius: 11px; color: #abc; } @media (max-width: 521px) {}', 'fixture.css').map((item) => item.property), ['padding', 'margin-inline', 'gap', 'font-size', 'border-radius', '@media', 'color']);
  assert.deepEqual(inspect('', 'fixture.css'), []);
  assert.equal(inspect('<template><div :style="{ paddingTop: \'7px\' }" /></template>', 'fixture.vue')[0]?.property, 'padding-top');
  assert.equal(inspect('@media (min-width: 480px) and (max-width: 521px) {}', 'fixture.css')[0]?.value, '521px');
});

test('all non-pending Vue and CSS files obey the design scales', () => {
  console.info('DESIGN_EXCEPTIONS:', JSON.stringify(DESIGN_EXCEPTIONS));
  console.info('PENDING_MIGRATION:', JSON.stringify(PENDING_MIGRATION));
  for (const entry of DESIGN_EXCEPTIONS) {
    assert.ok(entry.reason.length > 15, entry.file);
    assert.ok(readFileSync(join(ROOT, entry.file), 'utf8').includes(`${entry.property}: ${entry.value}`), `Excepción obsoleta: ${entry.file}: ${entry.value}`);
  }
  for (const [file] of PENDING_MIGRATION) assert.ok(existsSync(join(ROOT, file)), file);
  const violations: string[] = [];
  function scan(directory: string, relative = '') {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const file = relative + entry.name;
      if (PENDING_MIGRATION.some(([pending]) => file === pending || file.startsWith(pending.endsWith('/') ? pending : `${pending}/`))) continue;
      if (entry.isDirectory()) scan(join(directory, entry.name), `${file}/`);
      else if (/\.(vue|css)$/.test(file)) {
        for (const violation of inspect(readFileSync(join(ROOT, file), 'utf8'), file)) violations.push(`${file}: ${violation.property}: ${violation.value}`);
      }
    }
  }
  scan(ROOT);
  assert.deepEqual(violations, []);
});
