"""add sms_subscribers table

Revision ID: c1d2e3f4a5b6
Revises: 83163041013f
Create Date: 2026-06-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = '83163041013f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sms_subscribers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('phone_number', sa.String(), nullable=False),
        sa.Column('opted_in', sa.Boolean(), nullable=False),
        sa.Column('opted_in_at', sa.DateTime(), nullable=True),
        sa.Column('opted_out_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('phone_number'),
    )


def downgrade() -> None:
    op.drop_table('sms_subscribers')
