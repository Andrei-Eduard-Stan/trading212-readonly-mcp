# Trading 212 Read-Only MCP — Operations and Disaster Recovery

## Purpose

This repository implements a standalone authenticated Trading 212 read-only
MCP/data service.

Its purpose is to provide deterministic portfolio data and accounting to
ChatGPT and other authorised clients without exposing broker-side mutation
capabilities.

Architecture:

Trading 212 API
→ GET-only provider / normalization / pagination / caching
→ deterministic accounting
→ canonical portfolio snapshot/domain
→ authenticated MCP
→ ChatGPT / future consumers

## Security invariants

These are non-negotiable:

- Trading 212 access is strictly read-only.
- No order placement, modification, cancellation, or other broker mutation is exposed.
- Pies Write is not exposed.
- Orders Execute is not exposed.
- Broker secrets are never stored in Git.
- The MCP application binds only to `127.0.0.1:8000`.
- Public access is provided through Tailscale Funnel.
- SSH is permitted only through `tailscale0`.
- Unexpected firewall exposure fails closed.
- Unknown transaction or tax classifications fail closed.
- Recovery plaintext may exist only temporarily under `/run/trading212-recovery.*`
  and must be removed when bootstrap exits.

## Production identity

Service:

`portfolio-mcp.service`

Application:

`/opt/portfolio-hub`

Configuration and protected credentials:

`/etc/portfolio-hub`

Persistent state:

`/var/lib/portfolio-hub`

Local MCP listener:

`127.0.0.1:8000`

Canonical Tailscale hostname:

`portfolio-hub`

Canonical public hostname:

`portfolio-hub.tail894a11.ts.net`

Public MCP resource:

`https://portfolio-hub.tail894a11.ts.net/mcp`

Auth0 issuer:

`https://dev-portfolio-os-mcp.uk.auth0.com/`

Required OAuth scope:

`portfolio:read`

Do not treat a Tailscale IP address as permanent. Use the canonical hostname
or retrieve the current address with `tailscale ip -4`.

## Credential locations

Production Trading 212 credentials are held outside Git:

`/etc/portfolio-hub/trading212_api_key`

`/etc/portfolio-hub/trading212_api_secret`

Disaster recovery uses an encrypted `recovery.age` bundle.

The recovery passphrase/root of trust must be retained separately from the
server and repository.

Never print the Trading 212 credentials into terminals, logs, documentation,
issues, or chat.

## Accounting contract

Trading 212 `investments.totalCost` means current open-position cost basis.

Canonical field:

`openPositionCostBasis`

It must never be interpreted as deposits or total account contributions.

`unrealizedProfitLoss` is open-position unrealized P/L.

`realizedProfitLoss` is realized trading P/L and is not lifetime account return.

Lifetime monetary return is:

`accountValue - netAccountContributions`

Canonical contribution field:

`netAccountContributions`

Canonical annualized money-weighted return field:

`moneyWeightedReturnAnnualized`

Method:

XIRR

Time-weighted return must remain null unless sufficient historical valuations
exist at the required account-boundary cash-flow points.

Missing data must never be converted to zero.

Historical reconciliation differences must not be hidden with fabricated
adjustments.

## Supported recovery target

Certified recovery target:

Ubuntu 26.04 LTS

The recovery artifact contains:

- complete Git repository bundle
- exact recorded release commit
- restore script
- encrypted recovery bundle
- SHA-256 manifest

Recovery does not require GitHub credentials on the target server.

## Disaster recovery procedure

Copy the final DR kit to the blank Ubuntu host.

Run:

`sudo ./restore_from_kit.sh --kit /absolute/path/to/dr-kit`

The restore:

1. verifies the kit manifest;
2. verifies the complete Git bundle;
3. reconstructs the exact recorded commit;
4. validates or safely reuses a previously reconstructed repository;
5. materializes encrypted broker credentials temporarily under `/run`;
6. reconstructs Python and exact production dependencies;
7. deploys the application and systemd unit;
8. restores protected configuration;
9. verifies the Trading 212 credential contract;
10. validates the Tailscale identity;
11. configures Funnel;
12. converges UFW;
13. verifies loopback-only MCP exposure;
14. removes temporary recovery plaintext.

If Tailscale is not authenticated, the restore intentionally stops before
firewall exposure changes.

Authenticate with:

`sudo tailscale up --hostname=portfolio-hub`

Then verify:

- BackendState = Running
- HostName = portfolio-hub
- DNSName = portfolio-hub.tail894a11.ts.net.

Establish a working SSH session over Tailscale before rerunning bootstrap.

Then rerun the same restore command.

An interrupted restore may safely reuse an exact, clean, validated recovery
repository.

A recovery repository from a different release must fail closed rather than
being silently replaced.

## Acceptance checks

After restoration:

Temporary recovery plaintext:

`sudo find /run -maxdepth 1 -type d -name 'trading212-recovery*' -print`

Expected: no output.

Service:

`sudo systemctl is-active portfolio-mcp.service`

Expected: `active`

`sudo systemctl is-enabled portfolio-mcp.service`

Expected: `enabled`

Listener:

`sudo ss -ltnp | grep ':8000'`

Expected: `127.0.0.1:8000` only.

Firewall:

`sudo ufw status verbose`

Expected:

- active
- incoming deny
- outgoing allow
- SSH allowed only on `tailscale0`

Tailscale:

`sudo tailscale status`

Expected canonical node: `portfolio-hub`

Funnel:

`sudo tailscale funnel status`

Expected:

`https://portfolio-hub.tail894a11.ts.net`
→ `http://127.0.0.1:8000`

Unauthenticated MCP access:

`curl -sS -o /dev/null -w 'HTTP %{http_code}\n' https://portfolio-hub.tail894a11.ts.net/mcp`

Expected:

`HTTP 401`

Protected-resource metadata:

`https://portfolio-hub.tail894a11.ts.net/.well-known/oauth-protected-resource/mcp`

Expected:

- resource = canonical MCP URL
- authorization server = Auth0 issuer
- required scope = `portfolio:read`

A complete functional acceptance additionally requires an authenticated MCP
read that successfully reaches Trading 212 and returns the canonical portfolio
snapshot without exposing broker mutation operations.

## DR incidents discovered during destructive testing

### 1. Managed Python discovery

`uv 0.12.9` did not accept `--install-dir` for `uv python find`.

Fixed by using `UV_PYTHON_INSTALL_DIR` for discovery.

Fix commit:

`7e172a5`

### 2. Interrupted restore resumability

The initial restore wrapper removed a valid reconstructed repository after an
expected fail-closed bootstrap interruption and made retry behaviour awkward.

Fixed by distinguishing unvalidated clones from validated recovery repositories
and permitting exact clean repositories to be safely reused.

Fix commit:

`57d5190`

### 3. UFW interface token YAML coercion

Bare YAML `on` in an argv list was parsed as boolean `True`, producing:

`ufw allow in True tailscale0 ...`

Fixed by quoting the literal token:

`"on"`

Fix commit:

`678713c`

## Operational principle

Do not modify the broker integration to add write capability.

Do not weaken network controls to solve an availability problem.

Do not silently reinterpret accounting semantics.

Do not treat a successful process heartbeat as sufficient verification:
production acceptance requires authenticated live read behaviour.

When the system is working and the acceptance contract is satisfied, prefer
small, reviewed, reversible changes rather than continued redesign.
