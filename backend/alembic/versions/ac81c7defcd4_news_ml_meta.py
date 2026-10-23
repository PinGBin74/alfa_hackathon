"""news ml_meta

Revision ID: ac81c7defcd4
Revises: 0a401596e5ca
"""
from alembic import op
import sqlalchemy as sa


revision = 'ac81c7defcd4'
down_revision = '0a401596e5ca'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Полная разметка новости (факторы с направлением, страны, компании, важность): app.ml.news.NewsClassification.
    # Новости, записанные до миграции, остаются с NULL - разметка восстанавливается из колонок (news_meta).
    op.add_column('news', sa.Column('ml_meta', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('news', 'ml_meta')
