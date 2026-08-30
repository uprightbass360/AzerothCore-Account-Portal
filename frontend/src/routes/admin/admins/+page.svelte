<script lang="ts">
	import { enhance } from '$app/forms';
	import FieldErrors from '$lib/components/FieldErrors.svelte';
	let { data, form } = $props();
</script>

<svelte:head><title>Admins · Admin · Account Portal</title></svelte:head>

<section class="wow-card mb-6 p-6">
	<h2 class="wow-heading mb-4 text-lg">Grant portal admin</h2>
	{#if form?.granted}<p class="mb-2 text-sm text-q-uncommon">
			{form.granted} is now an admin.
		</p>{/if}
	<form method="POST" action="?/grant" use:enhance class="flex items-end gap-3">
		<div>
			<label class="mb-1 block text-sm" for="username">Game account username</label>
			<input
				id="username"
				name="username"
				value={form?.values?.username ?? ''}
				class="wow-input w-64 px-3 py-2"
			/>
			<FieldErrors errors={form?.errors?.username} />
		</div>
		<button class="btn-wow px-4 py-2 text-sm">Grant</button>
	</form>
	{#if form?.message}<p class="mt-2 text-sm text-red-400">{form.message}</p>{/if}
</section>

<section class="wow-panel">
	<h2 class="wow-heading border-b border-gold/20 px-5 py-3 text-lg">Portal admins</h2>
	<table class="w-full text-left text-sm">
		<tbody>
			{#each data.admins as a (a.account_id)}
				<tr class="border-t border-gold/10">
					<td class="px-5 py-2 font-medium">{a.username}</td>
					<td class="px-5 py-2 text-q-poor">
						since {new Date(a.granted_at).toLocaleDateString()}
						{a.granted_by === null ? '(env seed)' : ''}
					</td>
					<td class="px-5 py-2 text-right">
						<form method="POST" action="?/revoke" use:enhance>
							<input type="hidden" name="account_id" value={a.account_id} />
							<button class="text-red-400 hover:underline">Revoke</button>
						</form>
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
</section>
