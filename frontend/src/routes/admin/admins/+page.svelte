<script lang="ts">
	import { enhance } from '$app/forms';
	import FieldErrors from '$lib/components/FieldErrors.svelte';
	let { data, form } = $props();
</script>

<section class="mb-6 rounded border border-stone-300 bg-white p-5 shadow-sm">
	<h2 class="mb-3 font-medium">Grant portal admin</h2>
	{#if form?.granted}<p class="mb-2 text-sm text-green-700">{form.granted} is now an admin.</p>{/if}
	<form method="POST" action="?/grant" use:enhance class="flex items-end gap-3">
		<div>
			<label class="mb-1 block text-sm" for="username">Game account username</label>
			<input
				id="username"
				name="username"
				value={form?.values?.username ?? ''}
				class="w-64 rounded border border-stone-300 px-3 py-2"
			/>
			<FieldErrors errors={form?.errors?.username} />
		</div>
		<button class="rounded bg-stone-900 px-4 py-2 text-sm text-stone-100">Grant</button>
	</form>
	{#if form?.message}<p class="mt-2 text-sm text-red-600">{form.message}</p>{/if}
</section>

<section class="rounded border border-stone-300 bg-white shadow-sm">
	<h2 class="border-b border-stone-200 px-5 py-3 font-medium">Portal admins</h2>
	<table class="w-full text-left text-sm">
		<tbody>
			{#each data.admins as a (a.account_id)}
				<tr class="border-t border-stone-100">
					<td class="px-5 py-2 font-medium">{a.username}</td>
					<td class="px-5 py-2 text-stone-500">
						since {new Date(a.granted_at).toLocaleDateString()}
						{a.granted_by === null ? '(env seed)' : ''}
					</td>
					<td class="px-5 py-2 text-right">
						<form method="POST" action="?/revoke" use:enhance>
							<input type="hidden" name="account_id" value={a.account_id} />
							<button class="text-red-700 hover:underline">Revoke</button>
						</form>
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
</section>
