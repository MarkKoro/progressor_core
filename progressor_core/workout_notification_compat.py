"""Read-only fallback fence for the future free-workout admission protocol.

This shim never adopts the policy or creates its tables. Once either reserved
SQLite object exists, the fallback cannot certify new free activity and omits
its notification candidates. The full proof-aware reader is a separate release.
"""
import re
import sqlite3


POLICY_OBJECTS = ('free_workout_notification_policy',
                  'free_workout_notification_admissions')


def legacy_programmed_workout(workout):
    entity_id = workout.get('entity_id')
    return isinstance(entity_id, str) and re.fullmatch(r'workout:[1-9][0-9]*', entity_id) is not None


def suppress_free_notifications(store):
    """Object presence is durable; malformed or unreadable policy fails closed.

    SQLite identifiers ignore ASCII case. Do not inspect a reserved object's
    columns/rows/version or execute a view: even an empty or malformed object
    proves that returning to pre-policy free notification semantics is unsafe.
    Numeric programmed and other notification paths do not depend on this read.
    """
    try:
        with store.connection() as db:
            return db.execute('SELECT 1 FROM sqlite_master WHERE name COLLATE NOCASE IN (?,?) LIMIT 1',
                              POLICY_OBJECTS).fetchone() is not None
    except sqlite3.Error:
        return True
