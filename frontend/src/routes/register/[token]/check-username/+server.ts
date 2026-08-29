import { json } from '@sveltejs/kit';
import { api } from '$lib/server/api';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async (event) => {
	const username = event.url.searchParams.get('username') ?? '';
	const { status, data } = await api<{ valid: boolean; available: boolean }>(
		event,
		'GET',
		`/api/v1/register/${encodeURIComponent(event.params.token)}/check-username?username=${encodeURIComponent(username)}`
	);
	return json(data, { status });
};
