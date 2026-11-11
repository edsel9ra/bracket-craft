import { isThemePreference, normalizeTheme, THEME_COOKIE_NAME, THEME_COOKIE_OPTIONS, type ThemePreference } from '~/utils/theme';

export function useTheme() {
  const preference = useState<ThemePreference>('bc-theme-preference', () => {
    const cookie = useCookie<unknown>(THEME_COOKIE_NAME, {
      ...THEME_COOKIE_OPTIONS,
      secure: !import.meta.dev,
      readonly: true,
    });
    return normalizeTheme(cookie.value);
  });

  function setTheme(value: unknown): boolean {
    if (!isThemePreference(value)) return false;
    preference.value = value;
    if (import.meta.client) {
      try {
        document.cookie = `${THEME_COOKIE_NAME}=${value}; Path=${THEME_COOKIE_OPTIONS.path}; Max-Age=${THEME_COOKIE_OPTIONS.maxAge}; SameSite=Lax${import.meta.dev ? '' : '; Secure'}`;
      } catch {
        return true;
      }
    }
    return true;
  }

  return { preference: computed(() => preference.value), setTheme };
}
