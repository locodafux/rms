"""add record_events (filing / pullout / scanning history)

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-08-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # app.main calls Base.metadata.create_all on startup, so a dev database that
    # has run the new code already has this table. Creating it again would abort
    # the upgrade and leave the revision behind forever.
    if 'record_events' in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        'record_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('record_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('event_date', sa.Date(), nullable=True),
        sa.Column('data', sa.JSON(), nullable=True),
        sa.Column('source_job_id', sa.Integer(), nullable=True),
        sa.Column('dedupe_key', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['record_id'], ['records.id']),
        sa.ForeignKeyConstraint(['source_job_id'], ['import_jobs.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dedupe_key', name='uq_event_dedupe'),
    )
    op.create_index('ix_record_events_record_id', 'record_events', ['record_id'])
    op.create_index('ix_record_events_kind', 'record_events', ['kind'])
    op.create_index('ix_record_events_event_date', 'record_events', ['event_date'])
    op.create_index('ix_record_events_dedupe_key', 'record_events', ['dedupe_key'])


def downgrade() -> None:
    op.drop_table('record_events')
