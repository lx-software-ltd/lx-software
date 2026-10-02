import js from '@eslint/js'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
      jsxA11y.flatConfigs.recommended,
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
  },
  {
    files: ['src/components/ProjectCarousel.tsx'],
    rules: {
      // The project list is the carousel keyboard target: tabindex 0 and arrow keys.
      'jsx-a11y/no-noninteractive-tabindex': [
        'error',
        { tags: ['ul'], roles: ['tabpanel'], allowExpressionValues: true },
      ],
      'jsx-a11y/no-noninteractive-element-interactions': [
        'error',
        {
          handlers: [
            'onClick',
            'onError',
            'onLoad',
            'onMouseDown',
            'onMouseUp',
            'onKeyPress',
            'onKeyDown',
            'onKeyUp',
          ],
          ul: ['onKeyDown'],
          alert: ['onKeyUp', 'onKeyDown', 'onKeyPress'],
          body: ['onError', 'onLoad'],
          dialog: ['onKeyUp', 'onKeyDown', 'onKeyPress'],
          iframe: ['onError', 'onLoad'],
          img: ['onError', 'onLoad'],
        },
      ],
    },
  },
])
