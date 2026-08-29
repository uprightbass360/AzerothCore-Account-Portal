import { api } from '$lib/server/api';
import type { PageServerLoad } from './$types';

type AuditEntry = {
	at: string;
	actor_account_id: number | null;
	action: string;
	target: string;
	detail: unknown;
};

export const load: PageServerLoad = async (event) => {
	const action = event.url.searchParams.get('action') ?? '';
	const page = event.url.searchParams.get('page') ?? '1';
	const qs = new URLSearchParams({ action, page }).toString();
	const { data } = await api<{ items: AuditEntry[]; total: number; page: number; pages: number }>(
		event,
		'GET',
		`/api/v1/admin/audit?${qs}`
	);
	return {
		entries: data.items ?? [],
		total: data.total ?? 0,
		page: data.page ?? 1,
		pages: data.pages ?? 1,
		action
	};
};
