import { env } from '$env/dynamic/private';
import type { RequestEvent } from '@sveltejs/kit';

export type PortalUser = {
	username: string;
	email: string | null;
	totp_enabled: boolean;
	is_admin: boolean;
};

export type ApiResponse<T> = { status: number; data: T };

export async function api<T = Record<string, unknown>>(
	event: RequestEvent,
	method: string,
	path: string,
	body?: unknown
): Promise<ApiResponse<T>> {
	const headers: Record<string, string> = { 'X-Internal-Key': env.INTERNAL_API_KEY ?? '' };
	const token = event.cookies.get('session');
	if (token) headers['Authorization'] = `Bearer ${token}`;
	const init: RequestInit = { method, headers };
	if (body !== undefined) {
		headers['Content-Type'] = 'application/json';
		init.body = JSON.stringify(body);
	}
	const res = await event.fetch(`${env.BACKEND_URL}${path}`, init);
	const data = (await res.json().catch(() => ({}))) as T;
	return { status: res.status, data };
}

export function setSessionCookie(event: RequestEvent, token: string, expiresAt: string): void {
	event.cookies.set('session', token, {
		path: '/',
		httpOnly: true,
		sameSite: 'lax',
		secure: event.url.protocol === 'https:',
		expires: new Date(expiresAt)
	});
}

export function clearSessionCookie(event: RequestEvent): void {
	event.cookies.delete('session', { path: '/' });
}
