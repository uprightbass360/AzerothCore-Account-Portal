<script lang="ts">
	import { resolve } from '$app/paths';
	import './layout.css';
	import favicon from '$lib/assets/favicon.svg';

	let { data, children } = $props();
</script>

<svelte:head><link rel="icon" href={favicon} /></svelte:head>

<div class="min-h-screen">
	<nav
		class="border-b border-gold/30 bg-black/60 shadow-[0_10px_30px_rgba(0,0,0,.6)] backdrop-blur-md"
	>
		<div class="mx-auto flex max-w-4xl items-center gap-6 px-4 py-3">
			<a href={resolve('/')} class="wow-title text-xl">Account Portal</a>
			<div class="ml-auto flex items-center gap-5 text-sm">
				{#if data.user}
					<a href={resolve('/account')} class="text-questgold hover:text-gold-bright"
						>{data.user.username}</a
					>
					{#if data.user.is_admin}
						<a href={resolve('/admin/invites')} class="text-parchment/80 hover:text-gold-bright"
							>Admin</a
						>
					{/if}
					<form method="POST" action={resolve('/logout')}>
						<button class="text-parchment/60 hover:text-gold-bright">Log out</button>
					</form>
				{:else}
					<a href={resolve('/login')} class="text-questgold hover:text-gold-bright">Log in</a>
				{/if}
			</div>
		</div>
	</nav>
	<main class="mx-auto max-w-4xl px-4 py-10">
		{@render children()}
	</main>
</div>
