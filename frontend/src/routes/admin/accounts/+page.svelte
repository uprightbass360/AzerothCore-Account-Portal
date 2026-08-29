<script lang="ts">
	import { enhance } from '$app/forms';
	import { resolve } from '$app/paths';
	let { data, form } = $props();
</script>

<form method="GET" class="mb-4 flex gap-3">
	<input
		name="search"
		value={data.search}
		placeholder="Search username…"
		class="w-64 rounded border border-stone-300 px-3 py-2 text-sm"
	/>
	<button class="rounded bg-stone-900 px-4 py-2 text-sm text-stone-100">Search</button>
</form>
{#if form?.message}<p class="mb-3 text-sm text-red-600">{form.message}</p>{/if}

<div class="overflow-x-auto rounded border border-stone-300 bg-white shadow-sm">
	<table class="w-full text-left text-sm">
		<thead>
			<tr class="text-stone-500">
				<th class="px-4 py-2">Username</th><th class="px-4 py-2">Email</th>
				<th class="px-4 py-2">Joined</th><th class="px-4 py-2">Last login</th>
				<th class="px-4 py-2">2FA</th><th class="px-4 py-2">Status</th><th class="px-4 py-2"></th>
			</tr>
		</thead>
		<tbody>
			{#each data.accounts as a (a.id)}
				<tr class="border-t border-stone-100">
					<td class="px-4 py-2 font-medium"
						>{a.username}{#if a.is_admin}<span class="ml-1 rounded bg-stone-200 px-1 text-xs"
								>admin</span
							>{/if}</td
					>
					<td class="px-4 py-2">{a.email ?? a.invited_email ?? '—'}</td>
					<td class="px-4 py-2">{a.joindate ? new Date(a.joindate).toLocaleDateString() : '—'}</td>
					<td class="px-4 py-2"
						>{a.last_login ? new Date(a.last_login).toLocaleDateString() : '—'}</td
					>
					<td class="px-4 py-2">{a.totp_enabled ? 'on' : 'off'}</td>
					<td class="px-4 py-2">{a.locked ? '🔒 locked' : 'active'}</td>
					<td class="px-4 py-2 text-right">
						<form method="POST" action={a.locked ? '?/unlock' : '?/lock'} use:enhance>
							<input type="hidden" name="username" value={a.username} />
							<button class="hover:underline {a.locked ? 'text-stone-700' : 'text-red-700'}">
								{a.locked ? 'Unlock' : 'Lock'}
							</button>
						</form>
					</td>
				</tr>
			{:else}
				<tr><td class="px-4 py-3 text-stone-500" colspan="7">No accounts found.</td></tr>
			{/each}
		</tbody>
	</table>
</div>

{#if data.pages > 1}
	<div class="mt-4 flex gap-2 text-sm">
		{#each Array.from({ length: data.pages }, (_, i) => i + 1) as p (p)}
			<a
				href={resolve(`/admin/accounts?search=${data.search}&page=${p}`)}
				class="rounded px-3 py-1 {p === data.page ? 'bg-stone-900 text-stone-100' : 'bg-white'}"
				>{p}</a
			>
		{/each}
	</div>
{/if}
