"""Persist per-candidate metadata-origin provenance (#240).

Revision ID: 0015_candidate_metadata_origins
Revises: 0014_garmin_training_evidence
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_candidate_metadata_origins"
down_revision = "0014_garmin_training_evidence"
branch_labels = None
depends_on = None


def _restore_import_candidate_trigger() -> None:
    """Reinstall the terminal-candidate trigger including the new column.

    This migration only adds ``metadata_origins_json`` to
    ``import_candidates``.  It must not drop or rewrite canonical_selections
    triggers owned by 0002.
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
                NEW.metadata_origins_json IS NOT OLD.metadata_origins_json OR
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


def _restore_import_candidate_trigger_without_origins() -> None:
    """Restore the pre-0015 terminal-candidate trigger after downgrade."""

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
    """Add nullable per-candidate origin map; legacy NULL means not recorded."""

    with op.batch_alter_table("import_candidates") as batch:
        batch.add_column(sa.Column("metadata_origins_json", sa.Text(), nullable=True))
    _restore_import_candidate_trigger()


def downgrade() -> None:
    with op.batch_alter_table("import_candidates") as batch:
        batch.drop_column("metadata_origins_json")
    _restore_import_candidate_trigger_without_origins()
