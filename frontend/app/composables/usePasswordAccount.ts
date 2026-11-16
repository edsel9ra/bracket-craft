/** Llamadas de la spec 039; todas pasan por `useApi` (CSRF, cookies y SSR). */
export function usePasswordAccount() {
  const { request } = useApi();

  async function forgot(email: string): Promise<void> {
    await request('/auth/password/forgot', { method: 'POST', body: { email: email.trim() } });
  }

  async function reset(token: string, newPassword: string): Promise<void> {
    await request('/auth/password/reset', { method: 'POST', body: { token, new_password: newPassword } });
  }

  async function hasPassword(): Promise<boolean> {
    const response = await request<{ has_password: boolean }>('/auth/password');
    return response.has_password === true;
  }

  async function change(currentPassword: string, newPassword: string): Promise<void> {
    await request('/auth/password/change', {
      method: 'POST',
      body: { current_password: currentPassword, new_password: newPassword },
    });
  }

  return { forgot, reset, hasPassword, change };
}
