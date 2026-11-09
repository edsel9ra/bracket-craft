import withNuxt from './.nuxt/eslint.config.mjs';

export default withNuxt({
  ignores: ['e2e-report/**', 'playwright-report/**', 'test-results/**'],
  rules: {
    '@typescript-eslint/no-explicit-any': 'off',
    '@typescript-eslint/no-unused-vars': 'off',
    '@typescript-eslint/no-dynamic-delete': 'off',
    '@typescript-eslint/no-import-type-side-effects': 'off',
    'no-control-regex': 'off',
    'no-useless-assignment': 'off',
    'import/no-duplicates': 'off',
    'prefer-const': 'off',
    'vue/require-toggle-inside-transition': 'off',
    'vue/html-self-closing': 'off',
    'vue/attributes-order': 'off',
    'vue/attribute-hyphenation': 'off',
  },
});
