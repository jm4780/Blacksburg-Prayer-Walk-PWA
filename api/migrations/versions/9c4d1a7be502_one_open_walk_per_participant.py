"""one open walk per participant

Makes the one-open-walk rule a property of the database rather than of the application's
locking, and repairs any database that has already broken it.

Why this is a migration and not just an index on the model: docs/15-pilot-deployment.md
makes `alembic upgrade head` the only supported way to build the schema, so an index
declared on the model alone would simply be absent in the pilot — which is the one place
the rule has to hold.

Two steps, in order.

  1. **Repair.** A reviewer measured three simultaneous accepts leaving two open walks
     and eight leaving three, and found one participant holding three walks and
     seventy-one live street reservations at once. Those reservations are the harm:
     streets held against every other walker by walks nobody can see or finish. Any
     database this migration meets may already be in that state, and the unique index
     below cannot be created while it is. So the surplus walks are discarded first and
     their holds released — an ACTIVE walk always survives a PREVIEW one, and among
     equals the most recently created survives, which is the same preference
     `claim_walk_slot` applies.

  2. **The index.** Partial unique on `walks(participant_id)` where the status is open.
     PostgreSQL and SQLite both support partial indexes, so the pilot's database and the
     dev environment's enforce the identical rule.

Reversible: the downgrade drops the index. It does not un-discard the walks, because
those walks were surplus — restoring them would restore the defect.

Revision ID: 9c4d1a7be502
Revises: 7ec2c3ef667b
Create Date: 2026-08-11 17:40:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '9c4d1a7be502'
down_revision = '7ec2c3ef667b'
branch_labels = None
depends_on = None

INDEX_NAME = "uq_walk_one_open_per_participant"
OPEN = "status IN ('PREVIEW', 'ACTIVE')"

# Walks to discard, in two passes. Both are plain correlated subqueries so the same SQL
# runs on SQLite and PostgreSQL.
#
#   pass 1  a PREVIEW walk belonging to a participant who also has an ACTIVE one. The
#           commitment wins over the browse.
#   pass 2  an open walk that has a strictly newer open walk of its own kind. Ordering
#           by (created_at, id) is total, so exactly one survives per participant.
_LOSERS = (
    """
    SELECT w.id FROM walks w
     WHERE w.status = 'PREVIEW'
       AND EXISTS (SELECT 1 FROM walks o
                    WHERE o.participant_id = w.participant_id
                      AND o.status = 'ACTIVE')
    """,
    """
    SELECT w.id FROM walks w
     WHERE {open}
       AND EXISTS (SELECT 1 FROM walks o
                    WHERE o.participant_id = w.participant_id
                      AND o.status = w.status
                      AND (o.created_at > w.created_at
                           OR (o.created_at = w.created_at AND o.id > w.id)))
    """.format(open=OPEN),
)


def upgrade() -> None:
    for losers in _LOSERS:
        op.execute(sa.text(
            f"UPDATE reservations SET released_at = CURRENT_TIMESTAMP "
            f" WHERE released_at IS NULL AND walk_id IN ({losers})"))
        op.execute(sa.text(
            f"UPDATE walks SET status = 'DISCARDED', "
            f"       resolved_at = CURRENT_TIMESTAMP "
            f" WHERE id IN ({losers})"))

    op.create_index(INDEX_NAME, "walks", ["participant_id"], unique=True,
                    sqlite_where=sa.text(OPEN), postgresql_where=sa.text(OPEN))


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="walks")
