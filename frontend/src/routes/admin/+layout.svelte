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

<nav class="mb-6 flex gap-1 border-b border-gold/30 text-sm">
	{#each tabs as [href, label] (href)}
		<a
			href={resolve(href)}
			class="px-4 py-2 {page.url.pathname.startsWith(href)
				? 'border border-b-0 border-gold/40 bg-black/60 font-display font-bold text-questgold'
				: 'text-q-poor hover:text-gold-bright'}">{label}</a
		>
	{/each}
</nav>
{@render children()}
