import { describe, expect, it, vi } from 'vitest';
import type { RequestEvent } from '@sveltejs/kit';

vi.mock('$env/dynamic/private', () => ({
	env: { BACKEND_URL: 'http://backend.test', INTERNAL_API_KEY: 'k3y' }
}));

import { env } from '$env/dynamic/private';
import { api, clearSessionCookie, refreshSessionCookie, setSessionCookie } from './api';

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
		setSessionCookie(event, 'tok', '2027-01-01T00:00:00Z');
		expect(event.cookies.set).toHaveBeenCalledWith('session', 'tok', {
			path: '/',
			httpOnly: true,
			sameSite: 'lax',
			secure: true,
			expires: new Date('2027-01-01T00:00:00Z')
		});
		clearSessionCookie(event);
		expect(event.cookies.delete).toHaveBeenCalledWith('session', { path: '/' });
	});

	it('secure=false on http origins', () => {
		const event = makeEvent();
		(event as { url: URL }).url = new URL('http://localhost:3000/');
		setSessionCookie(event, 'tok', '2027-01-01T00:00:00Z');
		expect((event.cookies.set as ReturnType<typeof vi.fn>).mock.calls[0][2].secure).toBe(false);
	});
});

describe('refreshSessionCookie', () => {
	it('re-sets the session cookie ~7 days out when a session cookie is present', () => {
		const event = makeEvent('tok123');
		const before = Date.now();
		refreshSessionCookie(event);
		const after = Date.now();
		expect(event.cookies.set).toHaveBeenCalledTimes(1);
		const [name, token, opts] = (event.cookies.set as ReturnType<typeof vi.fn>).mock.calls[0];
		expect(name).toBe('session');
		expect(token).toBe('tok123');
		const expires = (opts as { expires: Date }).expires;
		const sevenDaysMs = 7 * 24 * 60 * 60 * 1000;
		expect(expires.getTime()).toBeGreaterThanOrEqual(before + sevenDaysMs);
		expect(expires.getTime()).toBeLessThanOrEqual(after + sevenDaysMs);
	});

	it('does nothing when there is no session cookie', () => {
		const event = makeEvent(undefined);
		refreshSessionCookie(event);
		expect(event.cookies.set).not.toHaveBeenCalled();
	});
});

describe('detail normalization', () => {
	async function apiWith(payload: unknown, status = 422) {
		const event = makeEvent();
		event.fetchMock.mockResolvedValue(new Response(JSON.stringify(payload), { status }));
		return api<Record<string, unknown>>(event, 'POST', '/x');
	}

	it('flattens FastAPI validation-error arrays into readable text', async () => {
		const res = await apiWith({
			detail: [
				{ loc: ['body', 'email'], msg: 'value is not a valid email address', type: 'value_error' },
				{ loc: ['body', 'other'], msg: 'field required', type: 'missing' }
			]
		});
		expect(res.data.detail).toBe('value is not a valid email address; field required');
	});

	it('handles array items without msg and empty arrays', async () => {
		expect((await apiWith({ detail: ['plain', 42] })).data.detail).toBe('plain; 42');
		expect((await apiWith({ detail: [] })).data.detail).toBe('Invalid input');
	});

	it('replaces non-array object details and preserves strings/absent', async () => {
		expect((await apiWith({ detail: { odd: true } })).data.detail).toBe('Invalid input');
		expect((await apiWith({ detail: 'kept as-is' })).data.detail).toBe('kept as-is');
		expect((await apiWith({ detail: null })).data.detail).toBeNull();
		expect((await apiWith({ ok: true })).data.detail).toBeUndefined();
		expect((await apiWith('not an object', 200)).data).toBe('not an object');
	});
});
