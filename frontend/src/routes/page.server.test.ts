import { describe, expect, it } from 'vitest';
import { load } from './+page.server';

describe('root load', () => {
	it('redirects logged-in users to /account', () => {
		expect(() => load({ locals: { user: { username: 'BOB' } } } as never)).toThrow(
			expect.objectContaining({ status: 303, location: '/account' })
		);
	});

	it('redirects anonymous users to /login', () => {
		expect(() => load({ locals: { user: null } } as never)).toThrow(
			expect.objectContaining({ status: 303, location: '/login' })
		);
	});
});
