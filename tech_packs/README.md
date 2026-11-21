# Tech packs

One YAML file per technology stack. In Stage 4 the solution design agent may only choose stacks that
have a pack here, and code checks that the pack supports the platform it is used for. A new stack
means a new pack, not new agents. Owners: tech lead and delivery head.

Fields:
- `name`: short id used in the design (file name without `.yaml`)
- `title`: human name
- `platforms`: which project platforms it can build (android, ios, web, admin_panel, backend)
- `approach`: native, cross_platform, web or backend
- `architecture`, `conventions`, `security`, `testing`: the rules developer agents and humans follow;
  Stage 5 tailors them into the project skill pack

These are v1 starting points written with Claude Code. Review and extend them with what the team
actually uses, and improve a pack after every finished project.
