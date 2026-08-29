import { expect, test } from '@playwright/test';

const BACKEND = process.env.PORTAL_E2E_BACKEND_URL ?? 'http://localhost:18000';
const KEY = process.env.PORTAL_INTERNAL_API_KEY ?? '';
const ADMIN_USER = process.env.PORTAL_E2E_ADMIN_USER ?? '';
const ADMIN_PASS = process.env.PORTAL_E2E_ADMIN_PASS ?? '';

async function backendApi(method: string, path: string, body?: unknown, token?: string) {
	const res = await fetch(`${BACKEND}${path}`, {
		method,
		headers: {
			'X-Internal-Key': KEY,
			'Content-Type': 'application/json',
			...(token ? { Authorization: `Bearer ${token}` } : {})
		},
		body: body ? JSON.stringify(body) : undefined
	});
	return { status: res.status, data: await res.json() };
}

test('admin login, password change, admin area', async ({ page }) => {
	test.skip(!KEY || !ADMIN_USER, 'set PORTAL_INTERNAL_API_KEY / PORTAL_E2E_ADMIN_USER(_PASS)');

	// Registration isn't exercised here: reading the invite token out of the mailer needs
	// SMTP pointed at MailHog (or similar) in the compose override, which isn't assumed
	// to be present for this smoke test.
	const login = await backendApi('POST', '/api/v1/auth/login', {
		username: ADMIN_USER,
		password: ADMIN_PASS
	});
	expect(login.status).toBe(200);

	// Portal login via UI with the admin account:
	await page.goto('/login');
	await page.getByLabel('Username').fill(ADMIN_USER);
	await page.getByLabel('Password').fill(ADMIN_PASS);
	await page.getByRole('button', { name: 'Log in' }).click();
	await expect(page).toHaveURL(/\/account$/);
	await expect(page.getByText(ADMIN_USER.toUpperCase())).toBeVisible();

	// Change password and back:
	await page.getByLabel('Current password').fill(ADMIN_PASS);
	await page.getByLabel('New password', { exact: true }).fill('e2eTmpPw1');
	await page.getByLabel('Confirm new password').fill('e2eTmpPw1');
	await page.getByRole('button', { name: 'Change password' }).click();
	await expect(page.getByText('Password changed')).toBeVisible();
	// restore
	await page.getByLabel('Current password').fill('e2eTmpPw1');
	await page.getByLabel('New password', { exact: true }).fill(ADMIN_PASS);
	await page.getByLabel('Confirm new password').fill(ADMIN_PASS);
	await page.getByRole('button', { name: 'Change password' }).click();
	await expect(page.getByText('Password changed')).toBeVisible();

	// Admin area loads:
	await page.goto('/admin/invites');
	await expect(page.getByText('Send an invite')).toBeVisible();
});
