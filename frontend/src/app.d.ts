// See https://svelte.dev/docs/kit/types#app.d.ts
// for information about these interfaces
import type { PortalUser } from '$lib/server/api';

declare global {
	namespace App {
		// interface Error {}
		interface Locals {
			user: PortalUser | null;
		}
		// interface PageData {}
		// interface PageState {}
		// interface Platform {}
	}
}

export {};
