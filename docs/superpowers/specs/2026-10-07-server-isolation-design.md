# 2-id Server Isolation Design

Date: 2026-10-07

## Scope

This design establishes the deployment boundary for the new `2-id` project on the shared host `91.107.240.235`. It does not deploy the application and does not modify the server. Product architecture and Telegram/payment implementation are intentionally deferred until the isolation baseline is accepted.

## Observed Baseline

The host was inspected read-only through Remote Desktop Commander before choosing project resources.

Active Docker containers observed:

- `pv-growth-app` on loopback port `8350`
- `akhbot-app` on loopback port `8307`
- `pv-reseller-dashboard` on loopback port `31080`
- `nine-router` on loopback port `20128`

Observed Docker networks:

- `pv_growth_net` — `172.23.77.0/24`
- `akhbot_internal` — `172.19.0.0/16`
- `pv_reseller_net` — `172.18.0.0/16`
- existing Docker bridge — `172.17.0.0/16`

The host also runs Apache on ports 80/443, MySQL, PostgreSQL, X-UI/Xray, Hedioum, SSH, WireGuard, GRE/SIT tunnels, `socat` forwarders, and PV-specific watchdog/forwarding services. These are shared production state and outside `2-id` ownership.

The root filesystem was about 95% full with roughly 2.2 GiB available. Docker reported 133 images using roughly 20.9 GB. No cleanup was performed.

## Selected Isolation Model

Use one dedicated Docker boundary on the existing Docker engine. This is preferred over sharing another project's network or introducing a second Docker daemon.

Project allocations:

| Resource | Allocation |
| --- | --- |
| Host directory | `/opt/2-id` |
| Container prefix | `twoid_` |
| Docker network | `twoid_internal` |
| Docker subnet | `172.28.235.0/24` |
| Volume prefix | `twoid_` |
| Candidate host ports | `127.0.0.1:18220-18229` |

The port range was free during the baseline inspection and is below the host's observed ephemeral range (`32768-60999`). The subnet did not appear in the observed host routing tables or Docker networks. Both facts must be revalidated immediately before deployment.

## Shared-Service Policy

Initial deployment must not depend on or alter Apache, existing databases, other Docker networks, host routes, WireGuard/GRE/SIT tunnels, Xray, Hedioum, or other production applications. Telegram long polling can operate without a public inbound bot port.

If a later feature requires a public webhook or admin panel, ingress integration is a separate design/change with an explicit review of the selected domain, port, TLS, and reverse-proxy behavior.

## Deployment Gate

Deployment is blocked until all of the following are true:

1. at least 5 GiB free space exists on the root filesystem;
2. selected ports remain unused;
3. `172.28.235.0/24` remains non-overlapping;
4. project secrets are provided outside Git;
5. a project-only rollback procedure exists;
6. existing production health is captured before the change.

Failure of any gate results in a stop and report, not modification of another service.

## Future Product Direction

The intended product is a reference Telegram service with a central API, wallet/payment layer, order engine, and partner integration keys so third-party bots can use the same backend. That product architecture must remain independent from the host isolation boundary defined here.

Apple account creation workers must expose a narrow job interface so the underlying worker implementation can change without coupling Telegram, wallet, or partner APIs to a private Apple protocol.

## Verification Strategy

Every production change will use before/after checks for:

- foreign container status;
- critical listening ports;
- Docker networks and routes;
- tunnel interfaces;
- disk/memory availability;
- `2-id` health;
- ability to roll back only `2-id` resources.

The repository-level enforcement rules are recorded in `/AGENTS.md`.
