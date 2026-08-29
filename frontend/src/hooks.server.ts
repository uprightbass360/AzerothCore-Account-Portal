import { redirect, type Handle } from '@sveltejs/kit';
import { api, clearSessionCookie, type PortalUser } from '$lib/server/api';

export const handle: Handle = async ({ event, resolve }) => {
	event.locals.user = null;
	if (event.cookies.get('session')) {
		const { status, data } = await api<PortalUser>(event, 'GET', '/api/v1/user');
		if (status === 200) event.locals.user = data;
		else clearSessionCookie(event);
	}
	const path = event.url.pathname;
	const needsAuth = path.startsWith('/account') || path.startsWith('/admin');
	if (needsAuth && !event.locals.user) redirect(303, '/login');
	if (path.startsWith('/admin') && !event.locals.user?.is_admin) redirect(303, '/account');
	return resolve(event);
};
