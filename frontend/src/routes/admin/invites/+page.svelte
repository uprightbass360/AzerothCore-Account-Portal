<script lang="ts">
	import { enhance } from '$app/forms';
	import FieldErrors from '$lib/components/FieldErrors.svelte';
	let { data, form } = $props();
</script>

<svelte:head><title>Invites · Admin · Account Portal</title></svelte:head>

<section class="wow-card mb-6 p-6">
	<h2 class="wow-heading mb-4 text-lg">Send an invite</h2>
	{#if form?.sent}<p class="mb-2 text-sm text-q-uncommon">Invite sent to {form.sent}.</p>{/if}
	<form method="POST" action="?/send" use:enhance class="flex items-end gap-3">
		<div>
			<label class="mb-1 block text-sm" for="email">Email address</label>
			<input
				id="email"
				name="email"
				value={form?.values?.email ?? ''}
				class="wow-input w-72 px-3 py-2"
			/>
			<FieldErrors errors={form?.errors?.email} />
		</div>
		<button class="btn-wow px-4 py-2 text-sm">Send invite</button>
	</form>
	{#if form?.message}<p class="mt-2 text-sm text-red-400">{form.message}</p>{/if}
</section>

<section class="wow-panel">
	<h2 class="wow-heading border-b border-gold/20 px-5 py-3 text-lg">Pending invites</h2>
	<div class="overflow-x-auto">
		<table class="w-full text-left text-sm">
			<thead>
				<tr class="text-q-poor">
					<th class="px-5 py-2">Email</th><th class="px-5 py-2">Sent</th>
					<th class="px-5 py-2">Expires</th><th class="px-5 py-2"></th>
				</tr>
			</thead>
			<tbody>
				{#each data.invites as inv (inv.id)}
					<tr class="border-t border-gold/10">
						<td class="px-5 py-2">{inv.email}</td>
						<td class="px-5 py-2">{new Date(inv.created_at).toLocaleDateString()}</td>
						<td class="px-5 py-2">{new Date(inv.expires_at).toLocaleDateString()}</td>
						<td class="px-5 py-2 text-right">
							<form method="POST" action="?/revoke" use:enhance>
								<input type="hidden" name="id" value={inv.id} />
								<button class="text-red-400 hover:underline">Revoke</button>
							</form>
						</td>
					</tr>
				{:else}
					<tr><td class="px-5 py-3 text-q-poor" colspan="4">No pending invites.</td></tr>
				{/each}
			</tbody>
		</table>
	</div>
</section>
