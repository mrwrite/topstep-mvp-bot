"""Add legal acceptance records

Revision ID: f3a4b5c6d7e8
Revises: f2a3b4c5d6e7
Create Date: 2026-06-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "legal_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_type", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column("content_url", sa.String(), nullable=True),
        sa.Column("required", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("effective_at", sa.DateTime(), nullable=False),
        sa.Column("document_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_legal_documents_id", "legal_documents", ["id"])
    op.create_index("ix_legal_documents_document_type", "legal_documents", ["document_type"])
    op.create_index("ix_legal_documents_version", "legal_documents", ["version"])
    op.create_index("ix_legal_documents_active", "legal_documents", ["active"])
    op.create_index("ux_legal_documents_type_version", "legal_documents", ["document_type", "version"], unique=True)
    op.create_index("ix_legal_documents_required_active", "legal_documents", ["required", "active"])

    op.create_table(
        "legal_acceptances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "legal_document_id",
            sa.Integer(),
            sa.ForeignKey("legal_documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("document_type", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=False),
        sa.Column("ip_hash", sa.String(), nullable=True),
        sa.Column("user_agent_summary", sa.String(), nullable=True),
        sa.Column("acceptance_metadata", sa.JSON(), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_legal_acceptances_id", "legal_acceptances", ["id"])
    op.create_index("ix_legal_acceptances_user_id", "legal_acceptances", ["user_id"])
    op.create_index("ix_legal_acceptances_legal_document_id", "legal_acceptances", ["legal_document_id"])
    op.create_index("ix_legal_acceptances_document_type", "legal_acceptances", ["document_type"])
    op.create_index("ix_legal_acceptances_version", "legal_acceptances", ["version"])
    op.create_index(
        "ux_legal_acceptances_user_document",
        "legal_acceptances",
        ["user_id", "legal_document_id"],
        unique=True,
    )
    op.create_index(
        "ix_legal_acceptances_user_type_version",
        "legal_acceptances",
        ["user_id", "document_type", "version"],
    )
    op.create_index("ix_legal_acceptances_user_accepted", "legal_acceptances", ["user_id", "accepted_at"])


def downgrade() -> None:
    op.drop_index("ix_legal_acceptances_user_accepted", table_name="legal_acceptances")
    op.drop_index("ix_legal_acceptances_user_type_version", table_name="legal_acceptances")
    op.drop_index("ux_legal_acceptances_user_document", table_name="legal_acceptances")
    op.drop_index("ix_legal_acceptances_version", table_name="legal_acceptances")
    op.drop_index("ix_legal_acceptances_document_type", table_name="legal_acceptances")
    op.drop_index("ix_legal_acceptances_legal_document_id", table_name="legal_acceptances")
    op.drop_index("ix_legal_acceptances_user_id", table_name="legal_acceptances")
    op.drop_index("ix_legal_acceptances_id", table_name="legal_acceptances")
    op.drop_table("legal_acceptances")

    op.drop_index("ix_legal_documents_required_active", table_name="legal_documents")
    op.drop_index("ux_legal_documents_type_version", table_name="legal_documents")
    op.drop_index("ix_legal_documents_active", table_name="legal_documents")
    op.drop_index("ix_legal_documents_version", table_name="legal_documents")
    op.drop_index("ix_legal_documents_document_type", table_name="legal_documents")
    op.drop_index("ix_legal_documents_id", table_name="legal_documents")
    op.drop_table("legal_documents")
