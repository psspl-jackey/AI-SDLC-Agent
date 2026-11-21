# Domain packs

One YAML file per product category. The research agent compares every brief against the matching pack,
so a new domain means a new pack, not new agents. Owners: tech lead and delivery head.

Fields:
- `name`, `aliases`: used to match the brief's domain
- `features`: `table_stakes` (users expect it) or `common` (many apps have it)
- `nfrs`: non-functional checks typical for the domain
- `compliance`: rules to check per region; always confirm with the client, these are prompts, not legal advice

Improve a pack after every finished project.
