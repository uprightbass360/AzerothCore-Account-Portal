import { env } from '$env/dynamic/private';
import type { RequestEvent } from '@sveltejs/kit';

export type PortalUser = {
	username: string;
	email: string | null;
	totp_enabled: boolean;
	is_admin: boolean;
};

// Mirrors the backend's session_ttl_days (backend/app/core/config.py). The backend
// slides sess.expires_at on every authenticated request; the browser cookie needs the
// same treatment or active users get logged out 7 days after login regardless of
// activity (the cookie would expire even though the server-side session is still valid).
const SESSION_TTL_DAYS = 7;

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
	normalizeDetail(data);
	return { status: res.status, data };
}

/**
 * FastAPI validation errors (422) carry `detail` as an array of error objects, which
 * would render as "[object Object]" wherever the UI shows `data.detail`. Flatten any
 * non-string detail into a readable message in place.
 */
function normalizeDetail(data: unknown): void {
	if (typeof data !== 'object' || data === null || !('detail' in data)) return;
	const record = data as Record<string, unknown>;
	const detail = record.detail;
	if (typeof detail === 'string' || detail === undefined || detail === null) return;
	if (Array.isArray(detail)) {
		const msgs = detail
			.map((item) =>
				typeof item === 'object' && item !== null && 'msg' in item
					? String((item as Record<string, unknown>).msg)
					: String(item)
			)
			.filter(Boolean);
		record.detail = msgs.length ? msgs.join('; ') : 'Invalid input';
	} else {
		record.detail = 'Invalid input';
	}
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

/**
 * Re-set the session cookie's expiry to now + the session TTL, matching the backend's
 * sliding-session renewal (see backend/app/core/deps.py). Call this whenever a request
 * with a valid session cookie succeeds, so an active user's cookie never expires while
 * their server-side session keeps being renewed underneath it.
 */
export function refreshSessionCookie(event: RequestEvent): void {
	const token = event.cookies.get('session');
	if (!token) return;
	const expiresAt = new Date(Date.now() + SESSION_TTL_DAYS * 24 * 60 * 60 * 1000).toISOString();
	setSessionCookie(event, token, expiresAt);
}
