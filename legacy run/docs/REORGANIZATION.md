# Source organization

Application code lives in `app/`, grouped by responsibility. Launch scripts live in `scripts/`, secondary entry points in `run/`, and developer tools and tests in their respective folders.

The legacy runtime is independent of the primary and secondary applications. Paths resolve from each application's configuration; source and policy loaders do not search sibling folders.

Backups, local checkpoints, model artifacts and runtime logs are not part of the public repository. See [maintenance](MAINTENANCE.md) for checks and [architecture](device_architecture.md) for runtime responsibilities.
