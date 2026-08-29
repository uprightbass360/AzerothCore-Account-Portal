<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	let { children } = $props();
	const tabs = [
		['/admin/invites', 'Invites'],
		['/admin/accounts', 'Accounts'],
		['/admin/admins', 'Admins'],
		['/admin/audit', 'Audit log']
	] as const;
</script>

<nav class="mb-6 flex gap-1 border-b border-stone-300 text-sm">
	{#each tabs as [href, label] (href)}
		<a
			href={resolve(href)}
			class="rounded-t px-4 py-2 {page.url.pathname.startsWith(href)
				? 'bg-white font-medium'
				: 'text-stone-500 hover:text-stone-800'}">{label}</a
		>
	{/each}
</nav>
{@render children()}
