This is Phosphor Deck's manual site (Astro + Starlight), published to
rsmedrano-cloud.github.io/phosphor-deck. The repo's own top-level AGENTS.md
(`../AGENTS.md`) governs Phosphor itself; this file is scoped to working
inside `site/` specifically.

**`src/content/docs/` and `src/assets/img/` are generated** by
`../doc/site/build.py` from `../doc/manual/*.md` and `../doc/img/` -- never
edit a page or image there by hand, edit the manual and rerun that script
(`python3 doc/site/build.py` from the repo root). `astro.config.mjs`,
`src/styles/phosphor.css` and everything else here is hand-kept.

## Development

When starting the dev server, use background mode:

```
astro dev --background
```

Manage the background server with `astro dev stop`, `astro dev status`, and `astro dev logs`.

## Documentation

Full documentation: https://docs.astro.build

Consult these guides before working on related tasks:

- [Adding pages, dynamic routes, or middleware](https://docs.astro.build/en/guides/routing/)
- [Working with Astro components](https://docs.astro.build/en/basics/astro-components/)
- [Using React, Vue, Svelte, or other framework components](https://docs.astro.build/en/guides/framework-components/)
- [Adding or managing content](https://docs.astro.build/en/guides/content-collections/)
- [Adding styles or using Tailwind](https://docs.astro.build/en/guides/styling/)
- [Supporting multiple languages](https://docs.astro.build/en/guides/internationalization/)
