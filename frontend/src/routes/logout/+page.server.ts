import { redirect } from '@sveltejs/kit';
import { api, clearSessionCookie } from '$lib/server/api';
import type { Actions } from './$types';

export const actions: Actions = {
	default: async (event) => {
		await api(event, 'POST', '/api/v1/auth/logout');
		clearSessionCookie(event);
		redirect(303, '/login');
	}
};
