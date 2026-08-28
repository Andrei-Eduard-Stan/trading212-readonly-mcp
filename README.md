# Trading 212 Read-Only MCP

Canonical source repository for the authenticated, strictly read-only Trading 212 data and MCP service originally deployed as Portfolio OS Secure Bootstrap.

## Baseline

The initial commit is a byte-identical capture of the verified production source running on `portfolio-hub`.

It intentionally preserves the production implementation before refactoring.

Production source hashes are recorded in:

`provenance/production-source-sha256.txt`

## Security boundary

- Trading 212 access is read-only.
- No order execution tools.
- No order cancellation or modification tools.
- No Pie write tools.
- Broker credentials are stored outside the repository.
- MCP access is OAuth-protected.
- Production secrets are not committed.

## Current structure

- `src/` — production Python source
- `deploy/` — production service definition
- `provenance/` — captured production runtime and source fingerprints

This repository will subsequently gain tests, dependency locking, reproducible deployment, disaster recovery, and reusable packaging without rewriting the original baseline history.
