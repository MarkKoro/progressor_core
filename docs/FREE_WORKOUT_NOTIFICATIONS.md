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
