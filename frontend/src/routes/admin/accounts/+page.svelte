<script lang="ts">
	import { enhance } from '$app/forms';
	import { resolve } from '$app/paths';
	let { data, form } = $props();
</script>

<svelte:head><title>Accounts · Admin · Account Portal</title></svelte:head>

<form method="GET" class="mb-4 flex items-center gap-3">
	<input
		name="search"
		value={data.search}
		placeholder="Search username…"
		class="wow-input w-64 px-3 py-2 text-sm"
	/>
	<label class="flex items-center gap-2 text-sm text-parchment/70">
		<input type="checkbox" name="bots" value="1" checked={data.bots} class="accent-gold" />
		Show bots
	</label>
	<button class="btn-wow px-3 py-2 text-sm">Search</button>
</form>
{#if form?.message}<p class="mb-3 text-sm text-red-400">{form.message}</p>{/if}
{#if form?.resetSent}
	<p class="mb-3 text-sm text-q-uncommon">
		Password reset — a new-password link was emailed to {form.resetSent}.
	</p>
{/if}

<div class="wow-panel overflow-x-auto">
	<table class="w-full text-left text-sm">
		<thead>
			<tr class="text-q-poor">
				<th class="px-3 py-2">Username</th><th class="px-3 py-2">Email</th>
				<th class="px-3 py-2">Joined</th><th class="px-3 py-2">Last login</th>
				<th class="px-3 py-2">2FA</th><th class="px-3 py-2">Status</th>
				<th class="px-3 py-2">Admin</th><th class="px-3 py-2"></th>
			</tr>
		</thead>
		<tbody>
			{#each data.accounts as a (a.id)}
				<tr class="border-t border-gold/10">
					<td class="px-3 py-2 font-medium">{a.username}</td>
					<td class="max-w-48 truncate px-3 py-2" title={a.email ?? a.invited_email ?? ''}
						>{a.email ?? a.invited_email ?? '—'}</td
					>
					<td class="px-3 py-2">{a.joindate ? new Date(a.joindate).toLocaleDateString() : '—'}</td>
					<td class="px-3 py-2"
						>{a.last_login ? new Date(a.last_login).toLocaleDateString() : '—'}</td
					>
					<td class="px-3 py-2 {a.totp_enabled ? 'text-q-uncommon' : 'text-q-poor'}"
						>{a.totp_enabled ? 'on' : 'off'}</td
					>
					<td class="px-3 py-2 {a.locked ? 'text-dk-red' : 'text-q-uncommon'}"
						>{a.locked ? 'Locked' : 'Active'}</td
					>
					<td class="px-3 py-2 whitespace-nowrap">
						{#if a.is_admin}
							<span class="border border-gold/40 px-1 text-xs text-questgold">admin</span>
							<form method="POST" action="?/revokeAdmin" use:enhance class="inline">
								<input type="hidden" name="account_id" value={a.id} />
								<button class="ml-1 text-xs text-q-poor hover:text-red-400 hover:underline"
									>remove</button
								>
							</form>
						{:else}
							<form method="POST" action="?/grantAdmin" use:enhance class="inline">
								<input type="hidden" name="username" value={a.username} />
								<button class="text-xs text-q-epic hover:underline">make admin</button>
							</form>
						{/if}
					</td>
					<td class="px-3 py-2 text-right">
						<div class="flex flex-col items-end gap-1 whitespace-nowrap">
							<form method="POST" action="?/resetPassword" use:enhance>
								<input type="hidden" name="username" value={a.username} />
								<button class="text-q-rare hover:underline">Reset password</button>
							</form>
							{#if a.username !== data.user?.username}
								<form method="POST" action={a.locked ? '?/unlock' : '?/lock'} use:enhance>
									<input type="hidden" name="username" value={a.username} />
									<button class="hover:underline {a.locked ? 'text-parchment/70' : 'text-red-400'}">
										{a.locked ? 'Unlock' : 'Lock'}
									</button>
								</form>
							{/if}
						</div>
					</td>
				</tr>
			{:else}
				<tr><td class="px-3 py-3 text-q-poor" colspan="8">No accounts found.</td></tr>
			{/each}
		</tbody>
	</table>
</div>

{#if data.pages > 1}
	<div class="mt-4 flex gap-2 text-sm">
		{#each Array.from({ length: data.pages }, (_, i) => i + 1) as p (p)}
			<a
				href={resolve(
					`/admin/accounts?${new URLSearchParams({ search: data.search, page: String(p) })}`
				)}
				class="border px-3 py-1 {p === data.page
					? 'border-gold-bright bg-black/60 text-questgold'
					: 'border-gold/20 bg-black/30 text-parchment/70 hover:text-gold-bright'}">{p}</a
			>
		{/each}
	</div>
{/if}
