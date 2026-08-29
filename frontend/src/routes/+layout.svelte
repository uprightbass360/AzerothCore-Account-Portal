<script lang="ts">
	import { resolve } from '$app/paths';
	import './layout.css';
	import favicon from '$lib/assets/favicon.svg';

	let { data, children } = $props();
</script>

<svelte:head><link rel="icon" href={favicon} /></svelte:head>

<div class="min-h-screen bg-stone-100 text-stone-900">
	<nav class="border-b border-stone-300 bg-stone-900 text-stone-100">
		<div class="mx-auto flex max-w-4xl items-center gap-6 px-4 py-3">
			<a href={resolve('/')} class="font-semibold tracking-wide">Account Portal</a>
			<div class="ml-auto flex items-center gap-4 text-sm">
				{#if data.user}
					<a href={resolve('/account')} class="hover:underline">{data.user.username}</a>
					{#if data.user.is_admin}
						<a href={resolve('/admin/invites')} class="hover:underline">Admin</a>
					{/if}
					<form method="POST" action={resolve('/logout')}>
						<button class="hover:underline">Log out</button>
					</form>
				{:else}
					<a href={resolve('/login')} class="hover:underline">Log in</a>
				{/if}
			</div>
		</div>
	</nav>
	<main class="mx-auto max-w-4xl px-4 py-8">
		{@render children()}
	</main>
</div>
