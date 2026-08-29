<script lang="ts">
	import { enhance } from '$app/forms';
	import FieldErrors from '$lib/components/FieldErrors.svelte';
	let { data, form } = $props();
</script>

<section class="mb-6 rounded border border-stone-300 bg-white p-5 shadow-sm">
	<h2 class="mb-3 font-medium">Send an invite</h2>
	{#if form?.sent}<p class="mb-2 text-sm text-green-700">Invite sent to {form.sent}.</p>{/if}
	<form method="POST" action="?/send" use:enhance class="flex items-end gap-3">
		<div>
			<label class="mb-1 block text-sm" for="email">Email address</label>
			<input
				id="email"
				name="email"
				value={form?.values?.email ?? ''}
				class="w-72 rounded border border-stone-300 px-3 py-2"
			/>
			<FieldErrors errors={form?.errors?.email} />
		</div>
		<button class="rounded bg-stone-900 px-4 py-2 text-sm text-stone-100">Send invite</button>
	</form>
	{#if form?.message}<p class="mt-2 text-sm text-red-600">{form.message}</p>{/if}
</section>

<section class="rounded border border-stone-300 bg-white shadow-sm">
	<h2 class="border-b border-stone-200 px-5 py-3 font-medium">Pending invites</h2>
	<div class="overflow-x-auto">
		<table class="w-full text-left text-sm">
			<thead>
				<tr class="text-stone-500">
					<th class="px-5 py-2">Email</th><th class="px-5 py-2">Sent</th>
					<th class="px-5 py-2">Expires</th><th class="px-5 py-2"></th>
				</tr>
			</thead>
			<tbody>
				{#each data.invites as inv (inv.id)}
					<tr class="border-t border-stone-100">
						<td class="px-5 py-2">{inv.email}</td>
						<td class="px-5 py-2">{new Date(inv.created_at).toLocaleDateString()}</td>
						<td class="px-5 py-2">{new Date(inv.expires_at).toLocaleDateString()}</td>
						<td class="px-5 py-2 text-right">
							<form method="POST" action="?/revoke" use:enhance>
								<input type="hidden" name="id" value={inv.id} />
								<button class="text-red-700 hover:underline">Revoke</button>
							</form>
						</td>
					</tr>
				{:else}
					<tr><td class="px-5 py-3 text-stone-500" colspan="4">No pending invites.</td></tr>
				{/each}
			</tbody>
		</table>
	</div>
</section>
