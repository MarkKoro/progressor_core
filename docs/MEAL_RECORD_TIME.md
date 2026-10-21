# Food journal dates and save-time provenance

Food owns its existing `meals.date` journal day. This remains the Moscow day;
changing the notification timezone does not move meals, totals, nutrients or
historical records between days. `created_at` records when the server saved the
entry. It does not establish when the person consumed the food.

The Food adapter keeps the existing UTC event envelope and journal day. It adds
optional `recorded_at`, `recorded_at_basis`, `consumed_at: null` and
`consumed_at_basis: not_reported` to meal payloads. A missing save timestamp stays
unknown in `recorded_at`; the existing day-midnight envelope fallback is not
eligible for a near-real-time reminder. The current adapter interprets legacy
naive timestamps in its established `Europe/Moscow` source timezone. An explicit
offset is converted as an instant. This change does not verify or change the
production host timezone, introduce a consumption clock or migrate native data.

An eligible Food save event must have a known save-time basis, an aware instant,
a valid source timezone, and a journal date equal to that instant's date in the
Food source timezone. A newly added historical or future-day entry therefore
does not become a current meal anchor. An ordinary 23:59 save remains eligible
just after midnight while its original instant is within the existing inclusive
10-minute freshness window. Do not compare the diary day with the current UTC
day or the Supply timezone. The established optional Supply slot window of
90 minutes is unchanged.

The Core reader also accepts previous adapter payloads that lack the new fields
but explicitly declare the existing `legacy_server_timezone` basis. It applies
the same journal-day guard. Unknown/malformed metadata is ineligible rather than
being guessed. Existing paid source/target, owner, source freshness, preferences,
Supply consent, rest and signed internal Supply-audience guards remain in force.

The Food API retains its legacy `time` field and adds `recorded_at` (raw native
server save value), `recorded_at_basis: server_save_time | missing`,
`recorded_display`, and `consumed_at: null`. The native journal and meal editor
label the value «Добавлено». A save on a different journal day displays its full
date as well as time. The native Excel export has separate diary-date and
«Добавлено» columns and retains the full saved date/time. No «МСК» label is added
to a raw server-local clock without a timezone conversion. Header cells wrap at
320 px / 200% text rather than increasing the mobile viewport.

This is a narrow time-provenance correction. The reachable native
`billing.save_meal(..., day=...)` writer supports a historical day, but no
existing end-user backdate UI was found during this review. The tests prove the
writer and projection boundary; they do not establish a production incident or
actual Telegram reminder delivery. A future consumed-time editor, day move or
raw-capture shelf needs a separate owner/version/retention design. It must
preserve nutrient-version matching and day-closure semantics.

Regression coverage: `tests/test_meal_recorded_time.py` exercises historical and
future days, Moscow/UTC/Bangkok offsets, midnight, missing and malformed values,
the exact 10-minute edge, source/access/rest/owner gates, edits/deletions and the
signed Supply-only route. Food's `tests/test_meal_recorded_provenance.py` checks
the owned API, unchanged rows and native Excel output;
`tests/meal-recorded-ui.test.cjs` checks actual native rendering at 320/390 px and
100/200% text. Deterministic reads introduce no AI, payment, push or consumer.
