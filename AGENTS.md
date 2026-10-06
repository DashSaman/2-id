# 2-id Repository Guardrails

These rules apply to every agent, operator, script, deployment, and automation working on this repository.

## Mission

`2-id` is an isolated service deployed on the shared production host `91.107.240.235` (`RoboT`). The host already runs production bots, dashboards, databases, web services, VPN/tunnel services, and Docker workloads. Preserving those workloads has priority over deploying or repairing `2-id`.

## Ownership Boundary

`2-id` may own only resources explicitly created for this project:

- host directory: `/opt/2-id`
- container names prefixed with `twoid_`
- Docker network: `twoid_internal`
- Docker subnet: `172.28.235.0/24`
- Docker volumes prefixed with `twoid_`
- host TCP ports `127.0.0.1:18220-18229`, after a fresh preflight confirms each requested port is free
- project-specific logs, configuration, secrets, images, and processes created under the `2-id` deployment

Anything outside this list is foreign production state and must be treated as read-only unless the user explicitly expands the boundary.

## Protected Production Resources

Never stop, restart, remove, rename, reconfigure, prune, disconnect, or reuse any existing resource belonging to another project. The protected baseline includes, but is not limited to:

- containers: `pv-growth-app`, `akhbot-app`, `pv-reseller-dashboard`, `nine-router`
- Docker networks: `akhbot_internal`, `pv_growth_net`, `pv_reseller_net`, `bridge`, `host`, `none`
- Docker subnets already in use: `172.18.0.0/16`, `172.19.0.0/16`, `172.23.77.0/24`, and Docker's existing `172.17.0.0/16`
- host projects under `/opt` other than `/opt/2-id`, including `akhbot`, `pv-growth`, `pv-reseller`, `mirza-custom`, `mirza-provider-v3`, `ov-node`, `pvnaive-worker`, and `sentinelx-worker`
- Apache and its existing virtual hosts
- MySQL and PostgreSQL host instances
- X-UI and Xray
- Hedioum
- WireGuard, GRE, SIT/IP tunnels, tunnel interfaces, routes, and policy routing
- `socat` forwarding processes
- PV watchdog/forwarder services
- host firewall, SSH, system networking, DNS, and systemd configuration not owned by `2-id`

## Forbidden Operations

The following operations are forbidden unless the user gives explicit, task-specific approval after the exact target and impact are shown:

- `docker system prune`, global Docker cleanup, or deleting unowned images/volumes/networks
- restarting or stopping the Docker daemon or `containerd`
- stopping/removing/recreating a container whose name does not start with `twoid_`
- modifying, disconnecting, or deleting a Docker network not owned by `2-id`
- deleting or modifying a Docker volume not prefixed with `twoid_`
- binding `2-id` directly to host ports `80`, `443`, or any currently occupied port
- changing Apache, X-UI/Xray, Hedioum, WireGuard, GRE/SIT, routes, firewall, MySQL, PostgreSQL, or other host production services
- changing another project's files, databases, credentials, environment, systemd units, tunnel configuration, or deployment
- broad destructive filesystem operations or cleanup outside `/opt/2-id`
- committing secrets, Telegram bot tokens, payment credentials, Apple credentials, API secrets, private keys, or production `.env` files to Git

## Mandatory Preflight Before Every Deploy or Restart

Before mutating the server, re-check live state. A historical inventory is never permission to assume a resource is still free.

At minimum verify:

1. the intended host ports are still free;
2. `172.28.235.0/24` does not overlap any current host route, tunnel, or Docker network;
3. the intended container, volume, and network names are exclusively `twoid_*` / `twoid_internal`;
4. no command will restart or recreate foreign containers;
5. root filesystem free space is at least 5 GiB before image pull/build/deployment;
6. current production containers and key host services are healthy before the change;
7. a rollback path exists that removes or restores only `2-id` resources.

If any preflight check fails, STOP. Do not make another production service fit around `2-id`.

## Disk Safety

The baseline inspection on 2026-10-07 found the root filesystem at approximately 95% usage with about 2.2 GiB free. This is below the deployment floor.

- Do not build or pull project images on this host while free space is below 5 GiB.
- Do not reclaim space by deleting foreign Docker images, volumes, logs, caches, or project files without explicit approval.
- If disk space blocks deployment, report the measured usage and stop.

## Network and Port Isolation

- Bind host-facing project ports to `127.0.0.1` only by default.
- The reserved candidate range is `18220-18229`; reservation is conditional on a fresh preflight.
- Use only `twoid_internal` with subnet `172.28.235.0/24` for project-internal traffic unless a future approved design changes it.
- Do not attach `2-id` containers to another project's Docker network.
- Do not modify host routes or tunnels to make `2-id` reachable.
- A public HTTP endpoint, reverse proxy, domain, TLS certificate, or payment webhook requires a separate approved change. Do not silently modify Apache.

## Data and Secret Isolation

- `2-id` gets its own database/storage; it must not reuse existing application databases on the host.
- Production secrets stay outside Git and are injected at runtime through project-owned secret/environment mechanisms.
- Never print secrets into logs, test output, CI artifacts, or operator messages.
- Apple/account credentials used by a job must have an explicit retention/deletion policy before production use.

## Deployment and Rollback

- Deployment commands must target explicit `twoid_*` resources; avoid global Docker selectors.
- Rollback may stop/remove only resources owned by `2-id`.
- Never use a rollback that restores the whole host, Docker directory, firewall, routes, Apache configuration, or another project's state.
- After each deployment, re-check existing production containers, critical listening ports, tunnels/routes, and `2-id` health.

## Stop Conditions

Stop and ask the user before proceeding if any action would require:

- touching a resource outside the ownership boundary;
- using a port outside the reserved range;
- changing Apache or another shared ingress service;
- changing firewall/routing/tunnel state;
- accessing another project's database or credentials;
- freeing disk space by deleting unowned data;
- restarting Docker/containerd or a shared host service;
- accepting a newly discovered conflict with production state.

Safety takes priority over completion speed. A blocked `2-id` deployment is preferable to changing a working production service.
