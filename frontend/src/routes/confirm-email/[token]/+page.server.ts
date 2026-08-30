import { fail } from '@sveltejs/kit';
import { api } from '$lib/server/api';
import type { Actions, PageServerLoad } from './$types';

type Detail = { detail?: string };

export const load: PageServerLoad = async (event) => {
	const { status, data } = await api<{ new_email?: string } & Detail>(
		event,
		'GET',
		`/api/v1/email-change/${encodeURIComponent(event.params.token)}`
	);
	if (status !== 200) return { invalid: data.detail ?? 'This confirmation link is not valid' };
	return { newEmail: data.new_email };
};

export const actions: Actions = {
	default: async (event) => {
		const { status, data } = await api<{ username?: string } & Detail>(
			event,
			'POST',
			`/api/v1/email-change/${encodeURIComponent(event.params.token)}`
		);
		if (status === 200) return { success: true, username: data.username };
		return fail(status, { message: data.detail ?? 'Confirmation failed' });
	}
};
