# Free workout notification fallback contract

Preparatory compatibility shim for H08-D, 26 October 2026. This shim does not fix
the free-workout clock/calendar reader, introduce source proof or adopt an
admission policy. It prepares a bounded fallback before the later coordinated
Gym/Core proof-aware release. The canonical implementation remains only in Core.

## Durable protocol names

The later proof-aware H08 implementation must use these reserved Core SQLite
table names, lowercase as written:

```sql
CREATE TABLE IF NOT EXISTS free_workout_notification_policy(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 protocol INTEGER NOT NULL CHECK(protocol=1),
 adopted_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS free_workout_notification_admissions(
 user_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 clock_bucket TEXT NOT NULL,
 source_activity_at TEXT,
 first_observed_at REAL NOT NULL,
 decision TEXT NOT NULL CHECK(decision IN ('admitted','denied','revoked')),
 reason TEXT NOT NULL,
 PRIMARY KEY(user_id,entity_id,clock_bucket)
);
```

These schemas are a future implementation contract, **not migration code in the
shim**. Full H08 must validate finite UTC epoch fields and canonical owner/entity
and clock buckets in its own writer. The singleton protocol1 row is initialized
once in the proof-aware adoption transaction with INSERT OR IGNORE. It is a
global anti-replay epoch, not an owner preference, paid entitlement, consent,
source action time or manual readiness gate. Restart/rollback/forward must reuse
it. Policy/admission tables must never be dropped to restore older behavior.

Admission is keyed by owner, exact free entity and the deterministic native UTC
clock bucket; it coalesces notification eligibility, not individual set writes.
The future admission writer admits only a first-observed valid native_touch
source clock T strictly after max(global adoption E,current Core
identities.created_at I), and not in the future. The future candidate reader
must independently enforce the same strict cutoff even for an already admitted
row. Missing/old/unknown clocks are terminally denied; later metadata repair
cannot promote them. Revocation is terminal within
the same bucket. Source absence, failure, expiry and rest are not deletion.
Owner erasure removes only that owner's admission/unknown-marker rows and keeps
the global singleton. Full H08 must install a dedicated identity-delete cleanup
trigger which persists during fallback; do not modify an existing trigger only
under CREATE IF NOT EXISTS and assume its old body changed. This shim creates
no tables, triggers, rows, epoch or admissions.

## Future owner incarnation cutoff — design only

The global epoch alone does not fence owner erasure: Core identity/preferences
and owned admission deletion can leave a genuine old Gym clock and older Food
opt-in in their independent native stores. A previously unseen/unreserved old
workout could otherwise be admitted again after re-import. This is a prospective
full-H08 design gap, not a reproduced production incident or a new public erase
API. The current shim remains conservative because it suppresses all free
triggers whenever a reserved policy object remains.

Full H08 must validate finite, timezone-aware UTC policy/identity instants and
require T>max(E,I) in BOTH admission and candidate selection. Missing, invalid or
future current identity state fails closed for free notification eligibility;
a read never creates an identity. Source membership reconciliation may recreate
I before its same-hash skip. Ordinary poll, restart, settings changes and reads
must not move an existing I. This identity/policy time never replaces saved
workout UTC, occurrence/completion/recording times or calendar dates. Equality
within the canonical source clock bucket remains conservatively ineligible.
New genuine activity strictly after the recreated I can qualify under all
existing source/target, freshness, native opt-in, rest, quiet, completion,
seen/day and Food reservation checks.

Erasure may remove owned admissions/unknown markers while retaining the global
epoch. A fresh I then fences old source history and stale retained admissions;
both the writer and candidate must apply it. A future reset which retains the
identity but clears admissions or pause fences must preserve conservative state
or atomically advance a declared notification-reset cutoff. Native Food clear
data is a separate opt-out path and must not be assumed to erase all Core or
Gym state. No new schema/writer/trigger/cutoff behavior is implemented here.

Ten full-H08 holdouts are planned, NOT executed by this shim or its19 tests:

|ID|Future required result|
|---|---|
|OR01|Pause/resume, Core identity erase and old-source re-import inside30min–2h: history retained, no stale new admission/push; native Food opt-in/paid rows unchanged.|
|OR02|Erased terminal denied/revoked bucket plus same-clock proof repair stays denied under fresh I.|
|OR03|Pre-global action remains denied through reset, as a negative control.|
|OR04|Genuine touch after fresh I and explicit/90min completion may qualify once.|
|OR05|Retained Food sent/reserved/uncertain day/key still blocks repeats; confirmed RetryAfter stays exact.|
|OR06|Real Food clear-data leaves opt-in off; re-enable advances native F; Core identity/global epoch and unrelated settings remain.|
|OR07|Missing identity read writes nothing; reconcile recreates I before hash-equal skip; metadata/restart cannot reopen old T.|
|OR08|Other owners, numeric programmed compatibility, paid grants, explicit review and meal anchors remain unchanged.|
|OR09|Full→shim→full across owner erasure retains global epoch; shim suppresses free and forward uses fresh I despite missing/stale admissions.|
|OR10|Normal poll/restart/settings keep I stable; any identity-preserving destructive reset needs its declared fence, unlike source failure/rest/expiry.|

## Fallback behavior

When neither reserved object exists, the existing notification behavior is
unchanged. When **either** reserved name exists in sqlite_master, the shim
suppresses every free or unclassified workout as a post-workout trigger. A name
with different ASCII case, wrong columns, missing rows, unknown version, view,
index or trigger is sufficient. It only reads sqlite_master and never executes
a reserved view or treats a malformed policy as absent. A SQLite inspection
error also suppresses this branch. It does not claim those malformed states are
healthy or repair them.

Only exact ASCII `workout:<positive decimal id>` remains on the programmed legacy
path. `workout:session:<id>`, missing identifiers, leading zero/Unicode/suffixed
forms and other malformed shapes cannot bypass suppression as numeric history.
Detection is performed once only if the enabled workout branch contains such a
nonprogrammed record. Numeric-only, weekly, weight and nutrient calculations
retain their prior rules. In a mixed list an eligible numeric session can still
trigger the ordinary post-workout message; a free session cannot independently
authorize it. Existing partial-session suppression and every access, source,
opt-in, rest, quiet-hour, seen/dismissed and Food day-completion check remain.

The shim deliberately does not inspect or grant an admitted receipt. Even a
genuine new free workout is suppressed while this degraded fallback runs.
Full H08 supplies proof-aware eligibility and restores eligible new free pushes;
old programmed timezone/history semantics remain a named compatibility limit.
No automatic food target, calories, dose, AI request, provider call, sender,
delivery key, reservation or retry changes are introduced.

## Release and guarantee boundary

Install this compatibility revision through the existing update-all engine
before the full H08 release so that it is the actual retained Core fallback.
Then a full→shim→full sequence retains the new tables/epoch/terminal decisions;
old Gym positional writes remain separately source-compatible and clear stale
proof through the later source triggers. Code rollback never restores live DBs.
The full release must verify the retained shim revision, its persistent owner
cleanup and the real rollback/forward matrix before publication.

The guarantee is narrow: new candidate calculations in this shim cannot produce
a free-triggered post-workout candidate while a policy object is observed, or
while policy inspection fails. It does not retroactively cancel a candidate
already returned before policy adoption, repair old UTC display/count behavior,
or protect arbitrary pre-shim readers. Dropping both reserved objects destroys
the durable adoption fact and is forbidden by the migration/recovery contract.
Deleting only their rows still keeps fallback suppression.

Meaningful synthetic checks cover real SQLite object inspection, no writes,
exact numeric and malformed identifiers, before/after candidate equivalence,
other notification priorities, mixed/partial lists, and inspection failure.
These are controlled unit scenarios, not a completed full H08 native/device or
production rollout. Provider and Telegram delivery are not exercised.


## Full H08 implementation — coordinated Gym/Core source, 28 October 2026

The sections above preserve the historical seventh compatibility contract and
its planned checks. This section describes the implemented full version; it
does not claim that the full version is already installed. The canonical Core
modules are workout_time.py, free_workout_notifications.py and Store's declared
startup/reconciliation hooks. Gym owns progressor_free_workout.py and the native
source witness; no second Core application or shared UI copy is introduced.

### Source time and read projections

Gym retains the six ordered progressor_free_sessions columns. Its separate
progressor_free_activity_proof row binds exact session id, last_activity scalar,
source date, validated IANA/exact UTC±HH:MM zone, version1 and native_touch.
Touch writes state then proof in the same native transaction. UPDATE OF
last_activity invalidates the old proof even when equal; insert/delete/session
delete and explicit owner cleanup prevent stale proof with foreign keys off.
Finish never writes or backfills proof and never assigns last_activity in its
conflict clause. Existing explicit/5400-second completion, operation receipts,
sets/repetitions and independent native access remain unchanged.

Core checks the whole clock/day/session/zone pairing. Genuine source UTC and
source local date survive profile travel. A transition ledger can describe a
continuous owner calendar interval after its first transition; it cannot prove
an action. Missing/malformed/legacy/no-state completion remains recorded_only
or not_recorded, without pretending current timezone or local midnight is the
activity time. Raw events/native history remain available; timed summaries,
comparisons and AI omit unknown time. context_snapshot also omits uncertain
exercise vectors after decode; raw data()/events retain them. The existing
known-time SQL91-day/+2-day margin is preserved.

Both AI selectors use the same known, completed, nonfuture14-day window capped
at20 summaries. Compact context retains time/day provenance and uncertainty;
it sends no detailed exercise vectors and makes no additional AI call. Day/week
coverage appears through existing rendered coverage text only for permitted,
ready Gym. Programmed exact ASCII workout:[1-9][0-9]* keeps its existing time
semantics; correcting historic programmed timezone matching is outside H08.

### Adoption, admission and owner incarnation

Store startup initializes the two reserved tables, global singleton protocol1 E,
dedicated identity-delete trigger and partial latest-unknown-marker index in its
normal transaction/savepoint only when both tables are absent. Existing valid E
is reused; malformed/partial objects fail closed for free notifications while
other Core operations remain available. Ordinary reads never initialize policy.
E is not a preference, entitlement, source time or new manual readiness gate.

Successful complete Gym reconciliation observes free clocks before the same-hash
skip and creates an owner's current identity before observing that owner.
Only first-observed native_touch T strictly after max(E,current identity I) and
not in the future may be admitted. Earlier/missing/invalid observations are
terminally denied. An admitted clock later observed invalid or successfully
deleted is terminally revoked. Same-clock metadata repair cannot reopen it;
new genuine activity must also pass the latest unknown/deletion floor. Source
read failure, source/access off, rest and expiry are not successful deletion.

Candidate selection independently validates policy, current canonical I, source
proof, terminal receipt and T>max(E,I,unknown floor), without writes. Missing,
future or malformed identity/policy state suppresses free candidates. Only
SQLite read errors are contained at the new metadata-connection boundary;
unrelated programming errors are not swallowed. Numeric and existing later
nutrient priorities can continue when free metadata cannot be read.

Identity erasure removes only that owner's admissions/unknown markers via the
dedicated persistent trigger and retains E. Re-import creates a fresh I before
hash-equal skipping, so old Gym activity and retained Food opt-in cannot replay.
Normal polls/restarts/settings do not advance I. Native Food clear-data remains
its separate opt-out/reset path. Other owners, paid records and native DBs are
not rewritten. Any future destructive reset retaining I must declare its own
atomic notification fence; do not infer one from ordinary settings changes.

Unchanged clocks use at most128-key composite-PK receipt probes per batch.
Latest unknown/deletion state uses its partial index; repeated successful
tombstones are idempotent. Do not replace this with unbounded admission scans
or one identity query/write per unchanged row.

### Delivery and recovery boundary

All earlier source/target access, freshness, consent, completion, preferences,
rest, quiet,30-minute–2-hour window, seen/dismissal and Food day-completion guards
remain additional requirements. Food owns reserved/sent/uncertain delivery and
confirmed RetryAfter state. H08 changes neither sender/reservation keys nor
Moscow Food days, goals, nutrients, targets, doses or provider calls.

The actual retained Core fallback is77d75b8d07fa1f125af973f3654c9a0203d189dd,
whose workout_notification_compat.py SHA256 is
80e78ba55d85f54e1ac004c82c4d2d2e7d418e71e45c763c54af9ecf624f3408.
It suppresses all free/unclassified candidates once either policy object exists,
including new valid activity, and does not provide the full UTC projection fix.
The dedicated cleanup trigger and native invalidation triggers survive code
rollback, so full→this shim→full preserves E, terminal decisions and owner-reset
boundaries. The coordinated release verifies that actual fallback before switch
and in strict checks. Never restore live DBs, drop objects or reset E to recover.

The existing unchanged update-all is the sole deployment engine. It has no new
generic H08 downgrade protocol/fence; arbitrary pre-shim/manual/forced main
replacement is unsupported and prohibited. Existing financial2/owner1/meal1
gates remain independent and cannot be described as an H08 downgrade fence.
After rollback with valid retained policy, retry must pin/reuse the same E rather
than treating the DB as a fresh absent-policy installation.

### Evidence and release gate

Focused synthetic suites cover22 native witness methods,25 reader methods and27
Core admission methods. Separate composed scenarios exercise actual native→Core
paths, owner reset, real Food delivery-state guards and whole retained fallback
subprocesses; overlapping scenarios are not additional unique unit counts.
Six older fixture files align their intended programmed/free positive controls
and current unknown-time negatives with these contracts; product guards remain.

The durable release journal binds exact source and evidence. Full canonical
Linux discovery for all four products, fresh whole-asset Node35, independent
review, a fresh bounded four-DB off-server restored pre-backup, ordinary main
fast-forwards, existing update-all, read-only live/schema/fallback verification
and a restored post-backup remain coordinated release requirements. Historical
settings UI evidence applies only to unchanged canonical assets; changed Gym
runtime is not an unchanged native tree or a new37-case device test. No real
Telegram delivery, paid provider, physical-device or human UX claim is made.


## Quoted schema literals — prepublication correction, 31 October 2026

Schema comparison preserves the exact case, inner whitespace and doubled quote
escapes of SQL string literals and quoted identifiers. Only whitespace outside
quotes is normalized; do not casefold whole DDL. In particular, changing the
admissions CHECK from 'admitted' to 'ADMITTED' changes its permitted values and
must fail closed rather than appear to be the canonical schema.

The regression demonstrates that old false positive using real SQLite DDL, then
checks fresh/valid retained adoption, malformed retained startup/read/observation
without ledger writes or epoch reset, and continued ordinary Core journal
reconciliation. It adds one method to the previous27 admission tests,28 total.
The matching operational inspector also preserves quoted bytes. Neither path
repairs, drops or replaces a malformed policy. Full release gates and actual
source-bound compound scenarios remain required for this corrected candidate.
