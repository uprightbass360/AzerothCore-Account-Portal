import { defineConfig } from '@playwright/test';

export default defineConfig({
	testDir: 'e2e',
	use: { baseURL: process.env.PORTAL_E2E_BASE_URL ?? 'http://localhost:8080' },
	retries: 0
});
