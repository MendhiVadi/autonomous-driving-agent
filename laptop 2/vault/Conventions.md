# Conventions

Read [[00-Index]] first and only the notes relevant to the task. Current code and
measured evidence take precedence over a stale note. Verify addresses and hardware live.
Update [[Architecture]], [[Decisions]], [[Session-Log]] and any affected contract or
connection note in the same task as a meaningful change. Keep notes concise and dated.

Never put passwords, tokens, private keys, raw datasets or binary checkpoints in
this vault. Reference their application-owned locations instead. Keep backups and
historical evidence separate from current instructions. Distinguish local rehearsals,
physical connection tests, simulator tests and learned-driving evaluations.

Root AGENTS.md governs laptop 1's agents. The portable client has its own AGENTS.md.
One AI tool writes at a time. Neither agent should modify the other PC's files
through the share during normal development.

## Snapshot updates

The root vault and `laptop 2/vault` initially contain identical files. Later changes
on laptop 2 are local until deliberately exchanged. Before refreshing its snapshot,
compare files and preserve divergent edits; do not overwrite them with an older copy.
Package updates are explicit, not a background synchronization service.

