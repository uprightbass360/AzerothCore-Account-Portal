import { fail, type RequestEvent } from '@sveltejs/kit';
import { api } from '$lib/server/api';
import type { Actions, PageServerLoad } from './$types';

type Detail = { detail?: string };
type Account = {
	id: number;
	username: string;
	email: string | null;
	joindate: string | null;
	last_login: string | null;
	totp_enabled: boolean;
	locked: boolean;
	is_admin: boolean;
	invited_email: string | null;
};

export const load: PageServerLoad = async (event) => {
	const search = event.url.searchParams.get('search') ?? '';
	const page = event.url.searchParams.get('page') ?? '1';
	const bots = event.url.searchParams.get('bots') === '1';
	const qs = new URLSearchParams({ search, page, bots: String(bots) }).toString();
	const { data } = await api<{ items: Account[]; total: number; page: number; pages: number }>(
		event,
		'GET',
		`/api/v1/admin/accounts?${qs}`
	);
	return {
		accounts: data.items ?? [],
		total: data.total ?? 0,
		page: data.page ?? 1,
		pages: data.pages ?? 1,
		search,
		bots
	};
};

async function act(event: RequestEvent, verb: 'lock' | 'unlock') {
	const fd = await event.request.formData();
	const { status, data } = await api<Detail>(
		event,
		'POST',
		`/api/v1/admin/accounts/${encodeURIComponent(String(fd.get('username')))}/${verb}`
	);
	if (status === 200) return { done: true };
	return fail(status, { message: data.detail ?? `${verb} failed` });
}

export const actions: Actions = {
	lock: (event) => act(event, 'lock'),
	unlock: (event) => act(event, 'unlock'),
	grantAdmin: async (event) => {
		const fd = await event.request.formData();
		const { status, data } = await api<Detail>(event, 'POST', '/api/v1/admin/admins', {
			username: String(fd.get('username'))
		});
		if (status === 201) return { adminChanged: true };
		return fail(status, { message: data.detail ?? 'Grant failed' });
	},
	revokeAdmin: async (event) => {
		const fd = await event.request.formData();
		const { status, data } = await api<Detail>(
			event,
			'DELETE',
			`/api/v1/admin/admins/${encodeURIComponent(String(fd.get('account_id')))}`
		);
		if (status === 200) return { adminChanged: true };
		return fail(status, { message: data.detail ?? 'Revoke failed' });
	},
	resetPassword: async (event) => {
		const fd = await event.request.formData();
		const username = encodeURIComponent(String(fd.get('username')));
		const { status, data } = await api<{ sent_to?: string } & Detail>(
			event,
			'POST',
			`/api/v1/admin/accounts/${username}/reset-password`
		);
		if (status === 200) return { resetSent: data.sent_to };
		return fail(status, { message: data.detail ?? 'Password reset failed' });
	}
};
