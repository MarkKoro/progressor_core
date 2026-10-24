# Supply intake timezone provenance

Core reads private owner snapshots. Changing Supply's current timezone changes
future reminders and the current profile clock. It does not relocate old intake
records. Intake identity, saved source day, recorded UTC, status and reported dose
remain source-owned. Recorded time is not a new claim of consumption time.

An intake timezone is optional metadata. Canonical Core `adapters.py` resolves it
from Supply's owner transition ledger, once per snapshot. Ledger user_id is a
Telegram subject; intake user_id is an internal Supply id. Never join the two
by an identically named column alone.

Only intervals after the first valid recorded transition have a defensible
lower bound. A continuous chain must end at the current source profile zone.
Known intervals emit `timezone` and `timezone_basis=owner_transition_ledger`.
Missing/empty history, records before the first transition, broken chains,
another owner or a current-zone mismatch emit `timezone_basis=not_recorded` and
omit timezone. A first `before_zone` does not prove all older legacy history.
Native SQLite records seconds; a cutover inside that saved second is also
unknown. Do not substitute today's zone, UTC or timezone=null for missing proof.

The event contract accepts omitted optional timezone. Source-local day/UTC/dose
still enter reconciliation, context and daily counts normally. The daily Supply
clock uses its current profile, while Food meal anchors retain their separate
Moscow/save-time contract. There is no owner write, new schema, migration,
consumer, gate or shared-helper mirror change.

A historical metadata correction may create the normal next Core entity
revision once during upgrade. It is not a change of today's account clock:
connection_changes records a timezone notice only for a base profile.updated
event. Genuine current-profile timezone changes still create that notice.

The H08-C baseline reproduced historical metadata changing UTC→Bangkok after a
native owner CAS, with no stored intake/day/UTC/dose/payment change. This bounded
fix removes that unproven relabeling. Tests cover optional metadata ingestion,
proven intervals, legacy unknowns, cutover ambiguity, owner isolation and invalid
lineage. They do not establish physical Telegram/device or human outcomes.
