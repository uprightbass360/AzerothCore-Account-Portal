<script lang="ts">
	import { resolve } from '$app/paths';
	let { data } = $props();
	const ACTIONS = [
		'',
		'invite.sent',
		'invite.redeemed',
		'invite.revoked',
		'account.created',
		'password.changed',
		'email.change_requested',
		'email.changed',
		'2fa.enabled',
		'2fa.disabled',
		'account.locked',
		'account.unlocked',
		'admin.granted',
		'admin.revoked',
		'login.success',
		'login.failed'
	];
</script>

<svelte:head><title>Audit log · Admin · Account Portal</title></svelte:head>

<form method="GET" class="mb-4 flex gap-3 text-sm">
	<select name="action" class="wow-input px-3 py-2">
		{#each ACTIONS as a (a)}
			<option value={a} selected={a === data.action}>{a || 'All actions'}</option>
		{/each}
	</select>
	<button class="btn-wow px-4 py-2">Filter</button>
</form>

<div class="wow-panel overflow-x-auto">
	<table class="w-full text-left text-sm">
		<thead>
			<tr class="text-q-poor">
				<th class="px-4 py-2">When</th><th class="px-4 py-2">Action</th>
				<th class="px-4 py-2">Target</th><th class="px-4 py-2">Actor</th>
				<th class="px-4 py-2">Detail</th>
			</tr>
		</thead>
		<tbody>
			{#each data.entries as e, i (i)}
				<tr class="border-t border-gold/10">
					<td class="px-4 py-2 whitespace-nowrap">{new Date(e.at).toLocaleString()}</td>
					<td class="px-4 py-2"><code class="text-xs">{e.action}</code></td>
					<td class="px-4 py-2">{e.target}</td>
					<td class="px-4 py-2">{e.actor_account_id ?? '—'}</td>
					<td class="px-4 py-2 text-xs text-q-poor">{e.detail ? JSON.stringify(e.detail) : ''}</td>
				</tr>
			{:else}
				<tr><td class="px-4 py-3 text-q-poor" colspan="5">No entries.</td></tr>
			{/each}
		</tbody>
	</table>
</div>

{#if data.pages > 1}
	<div class="mt-4 flex gap-2 text-sm">
		{#each Array.from({ length: data.pages }, (_, i) => i + 1) as p (p)}
			<a
				href={resolve(
					`/admin/audit?${new URLSearchParams({ action: data.action, page: String(p) })}`
				)}
				class="border px-3 py-1 {p === data.page
					? 'border-gold-bright bg-black/60 text-questgold'
					: 'border-gold/20 bg-black/30 text-parchment/70 hover:text-gold-bright'}">{p}</a
			>
		{/each}
	</div>
{/if}
