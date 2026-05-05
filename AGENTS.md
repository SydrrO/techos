# Deployment Safety Rules

This project has mutable production data on the server. Treat the server as the source of truth for runtime data.

Default server updates must preserve these production data files:

- `sydrro-data.sqlite3`
- `sydrro-backup.json`
- `data.xlsx`

Do not upload or overwrite those files during a normal code/UI deployment. Only push them when the user explicitly asks to overwrite server data, and make a server backup first.

Use these scripts instead of ad hoc `scp` commands:

- `scripts/deploy-server.ps1` updates code/config only by default.
- `scripts/deploy-server.ps1 -AllowDataOverwrite` is the explicit dangerous path for overwriting server data.
- `scripts/pull-server-data.ps1` downloads server data to local files after backing up the local copies.

Server details used by the scripts:

- SSH alias: `techos-server`
- Remote app path: `/opt/sydrro-techos`
- Service: `sydrro-techos`

