# Supply owner policy v1

Supply owns its current offer/privacy decision. Core consumes the result from
the same private SQLite copy as the subject and domain facts. Legal document
acceptance does not create a paid entitlement, source-sharing preference or
trainer permission. After enforcement, every personal Supply-origin cross-product
projection requires the owner's current decision in addition to the existing
paid, membership, source/target, freshness and purpose checks.

## One source and one copy

`Supply/legal_consent.py` is the only production implementation of the native
current-document predicate. `db.has_required_consent` and the batched exporter
call that same pure function with current Supply settings. Core stores no
required document versions and imports no Supply module.

The canonical `shared/progressor_client.py` accepts an optional owner metadata
writer. Its byte-identical mirrors live at each bot's `progressor_client.py`.
The hook runs on the temporary online-backup connection, before `quick_check`,
fsync and atomic replace. It never opens Core or updates the live native DB.
The existing ten-second budget also bounds SQLite work inside the hook; a
failure leaves the previous published copy unchanged, with normal freshness
expiry. The hook is trusted, owner-defined code, not an arbitrary plugin API.

Two tables are added only to the published copy:

* `progressor_owner_policy`: one schema-1 Supply header, opaque generation,
  timestamp, owner document versions and a stable semantic policy fingerprint.
* `progressor_owner_consent`: native `users.id`, exact decimal Telegram subject,
  strict 0/1 decision, bounded reason and matching policy fingerprint.

Core validates header shape, freshness, supported schema, identity and row
lineage. Missing, malformed, inconsistent or legacy metadata is unknown. A
new snapshot generation alone does not create user revisions or suggestions.
Fingerprints are lineage in an already private trusted artifact, not signatures.
No personal rows, fingerprints or accepted document versions belong in URLs or
public logs.

## Read semantics

The persistent gate is `/var/lib/progressor/owner-consent-v1-ready`.
With the gate present, unknown or closed owner decisions remove Supply from
personal context, AI context, shared profile fallback, Today, weekly totals,
weight choices/targets, change history, review hints, notifications and
meal-anchored delivery. A Supply receiving target must also be eligible for
contextual or proactive views, including Today, inline hints, AI context and
meal-anchored delivery.

The global own-account control menu is an intentional exception to that
receiving-product condition. After verification of the same personal account,
it can still show independently permitted Food/Gym settings, week and change
views while Supply is closed or unknown. Those sources retain their own paid,
membership, source-sharing and freshness checks; rest still pauses proactive
views. Supply-origin personal facts remain absent from these controls and
weight choices. The owner sync can continue carrying connection preferences,
rest state and an otherwise valid confirmed Food/Gym rhythm to the owner's
private settings cache. This control-plane exception neither opens Supply
facts nor grants trainer or AI access.

Native functions, paid terms, saved records and financial ledgers are unchanged.
Source ingestion and history retention are separate from this read policy;
enforcement is not a retroactive erasure job.

Current source/target payment and sharing choices still apply. Rest pauses
proactive context, summaries and reminders. Explicit own-account settings and
weight choices remain editable during rest; the owner legal boundary still
applies to them. Trainer access stays limited to separately permitted Food
daily macros and optional top-five dishes. Supply, labs and AI access are never
added to that trainer exception.

Core tracks semantic visibility epochs, independent of export generations.
On legal reopen or owner policy change, older Supply changes are hidden from
new projections; the boundary poll does not manufacture a new weight-change
suggestion. Commands confirmed before that new epoch are withheld until their
ordinary expiry. No missed notification or old review receipt is replayed.
Historical ledger entries are retained. A later genuine user edit may create a
new current suggestion.

The revocation bound remains the existing export/poll/freshness chain. This
does not provide an instantaneous remote revoke or retract delivered messages.
An actual native change made after the last published copy is observed only
after the next successful publication and Core poll; stale copies cease to be
eligible under the existing cutoff.

## Staged rollout and recovery

1. Deploy the owner writer, synchronized helper mirrors and protocol-1 Core
   parser/reader/updater while the ready gate is absent. This preserves the
   former policy in a shadow phase; it must not be presented as the new enforced
   protection. Record its start and a cutoff no later than 24 hours later.
2. Verify a fresh production private copy without logging users: one valid
   schema-1 header, matching fingerprint and subject coverage for eligible
   native users, no mixed/partial generation, DELETE journal, owner-only
   permissions, no WAL/SHM, unchanged consumer count and financial protocol 2.
3. Verify a tested protocol-1 reader and guarded updater in both the intended
   current runtime and recoverable fallback. There must be no unfinished updater
   transaction. Capture an application-consistent backup and independently
   restore-check it before changing the gate.
4. **Verify `/var/lib/progressor/owner-consent-v1-ready` backup and recovery
   coverage alongside `/var/lib/progressor/bundle-v2-ready`.** The coordinated
   updater now explicitly captures both present gates into its code/config tar,
   verifies exact bytes and mode, and records presence/hash/mode in the manifest.
   Missing gates are valid before activation; unreadable, symlink/nonregular,
   oversized or insecurely writable gates refuse backup. A gate changed during
   backup also refuses the result. The prior first-package standalone backup
   helper covered only the financial gate; the deployment owner must extend
   and independently restore-verify that separate coverage before activation.
   Never restore either gate to an older state while retaining newer code/data.
5. Activate the ready gate only after these checks, then independently verify
   strict mismatch/unknown behavior, current own subject, source off/rest/expiry,
   native fallback and healthy services. If the shadow cutoff cannot be met,
   stop/rollback the shadow rollout or explicitly close Supply projections;
   do not silently leave an indefinitely claimed protection. This cutoff is an
   operational gate, not an automatic timer that can bypass updater guards.

`OWNER_POLICY_PROTOCOL=1` and `OWNER_POLICY_UPDATER_PROTOCOL=1` are independent
of financial protocol 2. `update-all` checks the ready gate and literal markers
before candidate promotion, switching and updater replacement. It checks old
Core code, repository ref and saved installed updater before rollback, including
interrupted recovery. `update-progressor` delegates to the installed same engine.
An incompatible fallback is refused: current compatible code/runtime/updater are
retained, stopped services are resumed if safe, and the transaction reports
that recovery needs attention. This is not a successful rollback or healthy
release claim. No live SQLite is restored over newer user/payment writes.

A writer-only rollback after activation yields unknown Supply metadata rather
than reopening the old bool fallback. Keep the persistent ready gate in place.
Do not manually point Core at a pre-protocol release. The gate is not a defense
against a privileged operator deliberately bypassing the updater.

## Evidence and limits

Core's self-contained protocol tests exercise strict and shadow modes, malformed
metadata, exact large subjects, rest purpose, old changes, re-enable, source and
access gates, pending commands and signed ASGI routes. Supply tests compare the
real native predicate with the actual batched export over all flag/document
combinations and test copy consistency, captured settings, failure and deadline.
The separate journey probe exercises native SQLite → real owner backup and
metadata → adapters → Engine → signed routes. Linux filesystem/deployment gates
are required before production activation; Windows checks alone do not certify
Linux durability or a real provider/device flow. No test requires a charge, paid
AI request, real Telegram message or another consumer.
