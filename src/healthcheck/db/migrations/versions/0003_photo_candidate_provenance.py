"""Store extraction provider and field algorithm on import candidates.

Revision ID: 0003_photo_candidate_provenance
Revises: 0002_canonical_selection_metric_identity
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_photo_candidate_provenance"
down_revision = "0002_canonical_selection_metric_identity"
branch_labels = None
depends_on = None


def _restore_import_candidate_trigger() -> None:
    """Reinstall the R01-02 terminal-candidate trigger if SQLite rebuilt the table.

    This migration only adds columns to ``import_candidates``.  It must not
    drop or rewrite canonical_selections triggers owned by 0002.
    """

    op.execute("DROP TRIGGER IF EXISTS immutable_terminal_import_candidates_update")
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS immutable_terminal_import_candidates_update
        BEFORE UPDATE ON import_candidates
        WHEN OLD.user_decision <> 'pending'
        BEGIN
            SELECT CASE WHEN
                NEW.ingest_event_id IS NOT OLD.ingest_event_id OR
                NEW.candidate_set_key IS NOT OLD.candidate_set_key OR
                NEW.measurement_group_key IS NOT OLD.measurement_group_key OR
                NEW.metric_code IS NOT OLD.metric_code OR
                NEW.proposed_value IS NOT OLD.proposed_value OR
                NEW.proposed_unit IS NOT OLD.proposed_unit OR
                NEW.proposed_source_timestamp IS NOT OLD.proposed_source_timestamp OR
                NEW.proposed_source_local_date IS NOT OLD.proposed_source_local_date OR
                NEW.temporal_precision IS NOT OLD.temporal_precision OR
                NEW.source_text IS NOT OLD.source_text OR
                NEW.extractor_name IS NOT OLD.extractor_name OR
                NEW.extractor_version IS NOT OLD.extractor_version OR
                NEW.model_name IS NOT OLD.model_name OR
                NEW.model_version IS NOT OLD.model_version OR
                NEW.prompt_version IS NOT OLD.prompt_version OR
                NEW.schema_version IS NOT OLD.schema_version OR
                NEW.confidence IS NOT OLD.confidence OR
                NEW.evidence_region_json IS NOT OLD.evidence_region_json OR
                NEW.edited_value IS NOT OLD.edited_value OR
                NEW.edited_unit IS NOT OLD.edited_unit OR
                NEW.edited_source_timestamp IS NOT OLD.edited_source_timestamp OR
                NEW.edited_source_local_date IS NOT OLD.edited_source_local_date OR
                NEW.user_decision IS NOT OLD.user_decision OR
                NEW.decision_reason IS NOT OLD.decision_reason OR
                NEW.decision_at IS NOT OLD.decision_at OR
                NEW.created_at IS NOT OLD.created_at
            THEN RAISE(ABORT, 'terminal import candidates are immutable') END;
        END
        """
    )


def upgrade() -> None:
    """Retain per-candidate provider and algorithm identity from extraction."""

    with op.batch_alter_table("import_candidates") as batch:
        batch.add_column(sa.Column("algorithm_code", sa.String(180), nullable=True))
        batch.add_column(sa.Column("algorithm_version", sa.String(100), nullable=True))
        batch.add_column(sa.Column("provider_code", sa.String(120), nullable=True))
        batch.add_column(sa.Column("source_timezone", sa.String(100), nullable=True))
        batch.add_column(sa.Column("source_utc_offset_minutes", sa.Integer(), nullable=True))
    _restore_import_candidate_trigger()


def downgrade() -> None:
    with op.batch_alter_table("import_candidates") as batch:
        batch.drop_column("source_utc_offset_minutes")
        batch.drop_column("source_timezone")
        batch.drop_column("provider_code")
        batch.drop_column("algorithm_version")
        batch.drop_column("algorithm_code")
    _restore_import_candidate_trigger()
