import { describe, expect, it, vi } from 'vitest';
import type { RequestEvent } from '@sveltejs/kit';

vi.mock('$env/dynamic/private', () => ({
	env: { BACKEND_URL: 'http://backend.test', INTERNAL_API_KEY: 'k3y' }
}));

import { env } from '$env/dynamic/private';
import { api, clearSessionCookie, setSessionCookie } from './api';

function makeEvent(cookie?: string): RequestEvent & { fetchMock: ReturnType<typeof vi.fn> } {
	const fetchMock = vi
		.fn()
		.mockResolvedValue(new Response(JSON.stringify({ hello: 'world' }), { status: 200 }));
	return {
		fetch: fetchMock,
		fetchMock,
		url: new URL('https://portal.test/x'),
		cookies: {
			get: vi.fn().mockReturnValue(cookie),
			set: vi.fn(),
			delete: vi.fn()
		}
	} as unknown as RequestEvent & { fetchMock: ReturnType<typeof vi.fn> };
}

describe('api', () => {
	it('sends internal key, bearer, and json body', async () => {
		const event = makeEvent('tok123');
		const res = await api(event, 'POST', '/api/v1/auth/login', { a: 1 });
		expect(res).toEqual({ status: 200, data: { hello: 'world' } });
		const [url, init] = event.fetchMock.mock.calls[0];
		expect(url).toBe('http://backend.test/api/v1/auth/login');
		expect(init.headers['X-Internal-Key']).toBe('k3y');
		expect(init.headers['Authorization']).toBe('Bearer tok123');
		expect(init.headers['Content-Type']).toBe('application/json');
		expect(init.body).toBe(JSON.stringify({ a: 1 }));
	});

	it('omits bearer and body when absent', async () => {
		const event = makeEvent(undefined);
		await api(event, 'GET', '/api/v1/health');
		const [, init] = event.fetchMock.mock.calls[0];
		expect(init.headers['Authorization']).toBeUndefined();
		expect(init.body).toBeUndefined();
	});

	it('tolerates non-json responses', async () => {
		const event = makeEvent();
		event.fetchMock.mockResolvedValue(new Response('oops', { status: 502 }));
		const res = await api(event, 'GET', '/x');
		expect(res).toEqual({ status: 502, data: {} });
	});

	it('defaults the internal key header to empty string when unset', async () => {
		const original = env.INTERNAL_API_KEY;
		env.INTERNAL_API_KEY = undefined;
		try {
			const event = makeEvent();
			await api(event, 'GET', '/x');
			const [, init] = event.fetchMock.mock.calls[0];
			expect(init.headers['X-Internal-Key']).toBe('');
		} finally {
			env.INTERNAL_API_KEY = original;
		}
	});
});

describe('cookies', () => {
	it('sets and clears the session cookie', () => {
		const event = makeEvent();
		setSessionCookie(event, 'tok', '2027-01-01T00:00:00');
		expect(event.cookies.set).toHaveBeenCalledWith('session', 'tok', {
			path: '/',
			httpOnly: true,
			sameSite: 'lax',
			secure: true,
			expires: new Date('2027-01-01T00:00:00')
		});
		clearSessionCookie(event);
		expect(event.cookies.delete).toHaveBeenCalledWith('session', { path: '/' });
	});

	it('secure=false on http origins', () => {
		const event = makeEvent();
		(event as { url: URL }).url = new URL('http://localhost:3000/');
		setSessionCookie(event, 'tok', '2027-01-01T00:00:00');
		expect((event.cookies.set as ReturnType<typeof vi.fn>).mock.calls[0][2].secure).toBe(false);
	});
});
