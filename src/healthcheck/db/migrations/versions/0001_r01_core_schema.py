"""Create the R01 evidence, measurement and provenance schema.

Revision ID: 0001_r01_core_schema
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_r01_core_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the static R01-02 schema.

    This migration intentionally does not use the live ORM metadata.  Later
    R01/R02 tasks can add models without causing a fresh database to receive
    tables from a historical revision that predates them.
    """

    op.create_table(
        "providers",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("provider_kind", sa.String(80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_providers"),
        sa.UniqueConstraint("code", name="uq_providers_code"),
    )
    op.create_table(
        "physical_devices",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(160), nullable=False),
        sa.Column("manufacturer", sa.String(120), nullable=True),
        sa.Column("model", sa.String(120), nullable=True),
        sa.Column("instance_identifier", sa.String(200), nullable=True),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_physical_devices"),
        sa.UniqueConstraint("code", name="uq_physical_devices_code"),
    )
    op.create_table(
        "acquisition_sources",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(36), nullable=False),
        sa.Column("physical_device_id", sa.String(36), nullable=True),
        sa.Column("input_method", sa.String(40), nullable=False),
        sa.Column("source_instance_id", sa.String(36), nullable=True),
        sa.Column("source_application", sa.String(160), nullable=True),
        sa.Column("source_application_version", sa.String(80), nullable=True),
        sa.Column("configuration_snapshot_json", sa.Text(), nullable=True),
        sa.Column("configuration_fingerprint", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "input_method IN ('photo_import', 'webhook', 'provider_api', 'manual_import')",
            name="input_method_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["physical_device_id"], ["physical_devices.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_acquisition_sources"),
    )
    op.create_index(
        "ux_acquisition_sources_sender_instance_id",
        "acquisition_sources",
        ["source_instance_id"],
        unique=True,
        sqlite_where=sa.text("source_instance_id IS NOT NULL"),
    )
    op.create_index(
        "ux_acquisition_sources_natural_identity",
        "acquisition_sources",
        ["provider_id", "physical_device_id", "input_method"],
        unique=True,
        sqlite_where=sa.text("source_instance_id IS NULL AND physical_device_id IS NOT NULL"),
    )
    op.create_table(
        "measurement_algorithms",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(180), nullable=False),
        sa.Column("version", sa.String(100), nullable=False),
        sa.Column("metric_family", sa.String(100), nullable=False),
        sa.Column("producer", sa.String(100), nullable=False),
        sa.Column("parameters_json", sa.Text(), nullable=True),
        sa.Column("compatibility_group", sa.String(180), nullable=False),
        sa.Column("verification_state", sa.String(40), nullable=False, server_default="unknown"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_measurement_algorithms"),
        sa.UniqueConstraint("code", "version", name="uq_measurement_algorithms_code_version"),
    )
    op.create_table(
        "raw_artifacts",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("media_type", sa.String(160), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("relative_storage_path", sa.String(500), nullable=False),
        sa.Column("source_filename", sa.String(255), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("byte_size >= 0", name="byte_size_nonnegative"),
        sa.CheckConstraint("length(content_hash) >= 32", name="content_hash_min_length"),
        sa.CheckConstraint(
            "relative_storage_path NOT LIKE '/%' "
            "AND relative_storage_path NOT LIKE '\\\\%' "
            "AND relative_storage_path NOT GLOB '[A-Za-z]:*' "
            "AND relative_storage_path NOT LIKE '%..%'",
            name="relative_storage_path_only",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_raw_artifacts"),
        sa.UniqueConstraint("content_hash", name="uq_raw_artifacts_content_hash"),
    )
    op.create_table(
        "ingest_batches",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("acquisition_source_id", sa.String(36), nullable=False),
        sa.Column("batch_kind", sa.String(40), nullable=False),
        sa.Column("parser_name", sa.String(160), nullable=True),
        sa.Column("parser_version", sa.String(100), nullable=True),
        sa.Column("extractor_name", sa.String(160), nullable=True),
        sa.Column("extractor_version", sa.String(100), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="received"),
        sa.Column("received_count", sa.Integer(), nullable=True),
        sa.Column("parsed_count", sa.Integer(), nullable=True),
        sa.Column("committed_count", sa.Integer(), nullable=True),
        sa.Column("failed_count", sa.Integer(), nullable=True),
        sa.Column("diagnostic_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('received', 'parsed', 'pending-confirmation', 'committed', 'rejected', "
            "'duplicate', 'failed')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "batch_kind IN ('photo', 'webhook', 'provider_sync', 'manual')",
            name="batch_kind_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["acquisition_source_id"], ["acquisition_sources.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ingest_batches"),
    )
    op.create_table(
        "ingest_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("ingest_batch_id", sa.String(36), nullable=False),
        sa.Column("acquisition_source_id", sa.String(36), nullable=False),
        sa.Column("raw_artifact_id", sa.String(36), nullable=True),
        sa.Column("external_user_id", sa.String(255), nullable=True),
        sa.Column("provider_stream", sa.String(160), nullable=True),
        sa.Column("external_record_id", sa.String(255), nullable=True),
        sa.Column("semantic_fingerprint", sa.String(128), nullable=True),
        sa.Column("deduplication_key", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="received"),
        sa.Column("diagnostic_code", sa.String(100), nullable=True),
        sa.Column("diagnostic_reason", sa.Text(), nullable=True),
        sa.Column("duplicate_of_event_id", sa.String(36), nullable=True),
        sa.CheckConstraint(
            "status IN ('received', 'parsed', 'pending-confirmation', 'committed', 'rejected', "
            "'duplicate', 'failed')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "event_type IS NULL OR event_type IN "
            "('insert', 'update', 'delete', 'clear', 'test', 'photo')",
            name="event_type_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["acquisition_source_id"], ["acquisition_sources.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_of_event_id"], ["ingest_events.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["ingest_batch_id"], ["ingest_batches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["raw_artifact_id"], ["raw_artifacts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_ingest_events"),
    )
    op.create_index(
        "ux_ingest_events_deduplication_key",
        "ingest_events",
        ["deduplication_key"],
        unique=True,
    )
    op.create_table(
        "import_candidates",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("ingest_event_id", sa.String(36), nullable=False),
        sa.Column("candidate_set_key", sa.String(255), nullable=False),
        sa.Column("measurement_group_key", sa.String(255), nullable=False),
        sa.Column("metric_code", sa.String(120), nullable=False),
        sa.Column("proposed_value", sa.Float(), nullable=True),
        sa.Column("proposed_unit", sa.String(60), nullable=True),
        sa.Column("proposed_source_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proposed_source_local_date", sa.Date(), nullable=True),
        sa.Column("temporal_precision", sa.String(20), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("extractor_name", sa.String(160), nullable=True),
        sa.Column("extractor_version", sa.String(100), nullable=True),
        sa.Column("model_name", sa.String(160), nullable=True),
        sa.Column("model_version", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(100), nullable=True),
        sa.Column("schema_version", sa.String(100), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("evidence_region_json", sa.Text(), nullable=True),
        sa.Column("edited_value", sa.Float(), nullable=True),
        sa.Column("edited_unit", sa.String(60), nullable=True),
        sa.Column("edited_source_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("edited_source_local_date", sa.Date(), nullable=True),
        sa.Column("user_decision", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "user_decision IN ('pending', 'confirmed', 'rejected')", name="user_decision_allowed"
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"
        ),
        sa.CheckConstraint(
            "temporal_precision IS NULL OR temporal_precision IN ('instant', 'minute', 'date')",
            name="temporal_precision_allowed",
        ),
        sa.ForeignKeyConstraint(["ingest_event_id"], ["ingest_events.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_import_candidates"),
        sa.UniqueConstraint(
            "ingest_event_id",
            "candidate_set_key",
            "measurement_group_key",
            "metric_code",
            name="uq_import_candidates_semantic_field",
        ),
    )
    op.create_table(
        "import_candidate_edits",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("edited_fields_json", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(80), nullable=False, server_default="owner"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("revision >= 1", name="revision_positive"),
        sa.ForeignKeyConstraint(["candidate_id"], ["import_candidates.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_import_candidate_edits"),
        sa.UniqueConstraint("candidate_id", "revision", name="uq_candidate_edits_revision"),
    )
    op.create_table(
        "measurement_sessions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("acquisition_source_id", sa.String(36), nullable=False),
        sa.Column("ingest_event_id", sa.String(36), nullable=True),
        sa.Column("raw_artifact_id", sa.String(36), nullable=True),
        sa.Column("confirmation_candidate_id", sa.String(36), nullable=True),
        sa.Column("semantic_key", sa.String(255), nullable=True),
        sa.Column("source_record_id", sa.String(255), nullable=True),
        sa.Column("source_fingerprint", sa.String(128), nullable=True),
        sa.Column("temporal_precision", sa.String(20), nullable=False),
        sa.Column("source_local_date", sa.Date(), nullable=False),
        sa.Column("source_timestamp_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_local_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_utc_offset_minutes", sa.Integer(), nullable=True),
        sa.Column("source_timezone", sa.String(100), nullable=True),
        sa.Column("confirmation_status", sa.String(20), nullable=False, server_default="confirmed"),
        sa.Column("import_status", sa.String(40), nullable=False, server_default="committed"),
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("supersedes_session_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "temporal_precision IN ('instant', 'minute', 'date')", name="temporal_precision_allowed"
        ),
        sa.CheckConstraint(
            "(temporal_precision = 'date' AND source_timestamp_utc IS NULL "
            "AND source_local_timestamp IS NULL) "
            "OR (temporal_precision IN ('instant', 'minute') AND source_timestamp_utc IS NOT NULL)",
            name="temporal_precision_timestamp_consistency",
        ),
        sa.CheckConstraint(
            "source_utc_offset_minutes IS NULL OR "
            "(source_utc_offset_minutes >= -840 AND source_utc_offset_minutes <= 840)",
            name="source_utc_offset_range",
        ),
        sa.CheckConstraint(
            "confirmation_status IN ('confirmed', 'rejected', 'pending')",
            name="confirmation_status_allowed",
        ),
        sa.CheckConstraint("revision_number >= 1", name="revision_positive"),
        sa.ForeignKeyConstraint(
            ["acquisition_source_id"], ["acquisition_sources.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["confirmation_candidate_id"], ["import_candidates.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["ingest_event_id"], ["ingest_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["raw_artifact_id"], ["raw_artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["supersedes_session_id"], ["measurement_sessions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_measurement_sessions"),
    )
    op.create_index(
        "ix_measurement_sessions_source_identity",
        "measurement_sessions",
        ["acquisition_source_id", "semantic_key", "revision_number"],
    )
    op.create_index(
        "ux_measurement_sessions_semantic_revision",
        "measurement_sessions",
        ["acquisition_source_id", "semantic_key", "revision_number"],
        unique=True,
        sqlite_where=sa.text("semantic_key IS NOT NULL"),
    )
    op.create_index(
        "ux_measurement_sessions_source_record_revision",
        "measurement_sessions",
        ["acquisition_source_id", "source_record_id", "revision_number"],
        unique=True,
        sqlite_where=sa.text("source_record_id IS NOT NULL"),
    )
    op.create_index(
        "ux_measurement_sessions_source_fingerprint_revision",
        "measurement_sessions",
        ["acquisition_source_id", "source_fingerprint", "revision_number"],
        unique=True,
        sqlite_where=sa.text("source_fingerprint IS NOT NULL"),
    )
    op.create_index(
        "ux_measurement_sessions_confirmation_candidate",
        "measurement_sessions",
        ["confirmation_candidate_id"],
        unique=True,
        sqlite_where=sa.text("confirmation_candidate_id IS NOT NULL"),
    )
    op.create_index(
        "ux_measurement_sessions_single_successor",
        "measurement_sessions",
        ["supersedes_session_id"],
        unique=True,
        sqlite_where=sa.text("supersedes_session_id IS NOT NULL"),
    )
    op.create_table(
        "scalar_measurements",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("measurement_session_id", sa.String(36), nullable=False),
        sa.Column("import_candidate_id", sa.String(36), nullable=True),
        sa.Column("metric_code", sa.String(120), nullable=False),
        sa.Column("normalized_value", sa.Float(), nullable=False),
        sa.Column("normalized_unit", sa.String(60), nullable=False),
        sa.Column("original_value", sa.Text(), nullable=True),
        sa.Column("original_unit", sa.String(60), nullable=True),
        sa.Column("measurement_algorithm_id", sa.String(36), nullable=False),
        sa.Column("quality_status", sa.String(80), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("supersedes_measurement_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("length(metric_code) > 0", name="metric_code_nonempty"),
        sa.CheckConstraint("length(normalized_unit) > 0", name="normalized_unit_nonempty"),
        sa.ForeignKeyConstraint(
            ["import_candidate_id"], ["import_candidates.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["measurement_algorithm_id"], ["measurement_algorithms.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["measurement_session_id"], ["measurement_sessions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_measurement_id"], ["scalar_measurements.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scalar_measurements"),
        sa.UniqueConstraint(
            "measurement_session_id", "metric_code", name="uq_scalar_measurements_session_metric"
        ),
    )
    op.create_index(
        "ix_scalar_measurements_metric_session",
        "scalar_measurements",
        ["metric_code", "measurement_session_id"],
    )
    op.create_index(
        "ux_scalar_measurements_import_candidate_metric",
        "scalar_measurements",
        ["import_candidate_id", "metric_code"],
        unique=True,
        sqlite_where=sa.text("import_candidate_id IS NOT NULL"),
    )
    op.create_index(
        "ux_scalar_measurements_single_successor",
        "scalar_measurements",
        ["supersedes_measurement_id"],
        unique=True,
        sqlite_where=sa.text("supersedes_measurement_id IS NOT NULL"),
    )
    op.create_table(
        "derived_measurements",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("metric_code", sa.String(120), nullable=False),
        sa.Column("normalized_value", sa.Float(), nullable=False),
        sa.Column("normalized_unit", sa.String(60), nullable=False),
        sa.Column("algorithm_code", sa.String(180), nullable=False),
        sa.Column("algorithm_version", sa.String(100), nullable=False),
        sa.Column("parameters_json", sa.Text(), nullable=True),
        sa.Column("input_measurement_ids_json", sa.Text(), nullable=True),
        sa.Column("input_set_hash", sa.String(128), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("source_session_id", sa.String(36), nullable=True),
        sa.CheckConstraint("length(metric_code) > 0", name="metric_code_nonempty"),
        sa.CheckConstraint("length(normalized_unit) > 0", name="normalized_unit_nonempty"),
        sa.CheckConstraint(
            "input_measurement_ids_json IS NOT NULL OR input_set_hash IS NOT NULL",
            name="input_provenance_required",
        ),
        sa.ForeignKeyConstraint(
            ["source_session_id"], ["measurement_sessions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_derived_measurements"),
    )
    op.create_table(
        "canonical_rule_sets",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("rule_name", sa.String(160), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("effective_start_date", sa.Date(), nullable=True),
        sa.Column("effective_end_date", sa.Date(), nullable=True),
        sa.Column("rule_definition_json", sa.Text(), nullable=False),
        sa.Column("rule_hash", sa.String(128), nullable=False),
        sa.Column("creation_reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "effective_start_date IS NULL OR effective_end_date IS NULL "
            "OR effective_start_date <= effective_end_date",
            name="effective_period_order",
        ),
        sa.CheckConstraint("rule_version >= 1", name="rule_version_positive"),
        sa.PrimaryKeyConstraint("id", name="pk_canonical_rule_sets"),
        sa.UniqueConstraint(
            "rule_name", "rule_version", name="uq_canonical_rule_sets_name_version"
        ),
    )
    op.create_table(
        "canonical_selection_runs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("scope_key", sa.String(255), nullable=False),
        sa.Column("requested_start_date", sa.Date(), nullable=True),
        sa.Column("requested_end_date", sa.Date(), nullable=True),
        sa.Column("rule_set_id", sa.String(36), nullable=False),
        sa.Column("rule_name", sa.String(160), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("rule_hash", sa.String(128), nullable=False),
        sa.Column("input_snapshot_hash", sa.String(128), nullable=False),
        sa.Column("scope_json", sa.Text(), nullable=True),
        sa.Column("software_version", sa.String(100), nullable=True),
        sa.Column("build_version", sa.String(160), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("selection_count", sa.Integer(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("supersedes_run_id", sa.String(36), nullable=True),
        sa.CheckConstraint("status IN ('running', 'succeeded', 'failed')", name="status_allowed"),
        sa.CheckConstraint(
            "selection_count IS NULL OR selection_count >= 0", name="selection_count_nonnegative"
        ),
        sa.ForeignKeyConstraint(["rule_set_id"], ["canonical_rule_sets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["supersedes_run_id"], ["canonical_selection_runs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_canonical_selection_runs"),
    )
    op.create_index(
        "ux_canonical_successful_input",
        "canonical_selection_runs",
        ["scope_key", "rule_hash", "input_snapshot_hash"],
        unique=True,
        sqlite_where=sa.text("status = 'succeeded'"),
    )
    op.create_table(
        "canonical_selections",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("selection_run_id", sa.String(36), nullable=False),
        sa.Column("metric_code", sa.String(120), nullable=False),
        sa.Column("semantic_key", sa.String(255), nullable=False),
        sa.Column("period_start_date", sa.Date(), nullable=True),
        sa.Column("period_end_date", sa.Date(), nullable=True),
        sa.Column("source_measurement_id", sa.String(36), nullable=True),
        sa.Column("derived_measurement_id", sa.String(36), nullable=True),
        sa.Column("selection_reason", sa.Text(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "(source_measurement_id IS NOT NULL AND derived_measurement_id IS NULL) "
            "OR (source_measurement_id IS NULL AND derived_measurement_id IS NOT NULL)",
            name="exactly_one_evidence_reference",
        ),
        sa.ForeignKeyConstraint(
            ["derived_measurement_id"], ["derived_measurements.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["selection_run_id"], ["canonical_selection_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_measurement_id"], ["scalar_measurements.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_canonical_selections"),
        sa.UniqueConstraint(
            "selection_run_id", "semantic_key", name="uq_canonical_selections_run_key"
        ),
    )
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(36), nullable=False),
        sa.Column("acquisition_source_id", sa.String(36), nullable=True),
        sa.Column("stream_code", sa.String(160), nullable=False),
        sa.Column("requested_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("item_count", sa.Integer(), nullable=True),
        sa.Column("received_count", sa.Integer(), nullable=True),
        sa.Column("accepted_count", sa.Integer(), nullable=True),
        sa.Column("failed_count", sa.Integer(), nullable=True),
        sa.Column("error_category", sa.String(100), nullable=True),
        sa.Column("diagnostic_reason", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'partial', 'failed')", name="status_allowed"
        ),
        sa.CheckConstraint("item_count IS NULL OR item_count >= 0", name="item_count_nonnegative"),
        sa.CheckConstraint(
            "received_count IS NULL OR received_count >= 0", name="received_count_nonnegative"
        ),
        sa.CheckConstraint(
            "accepted_count IS NULL OR accepted_count >= 0", name="accepted_count_nonnegative"
        ),
        sa.CheckConstraint(
            "failed_count IS NULL OR failed_count >= 0", name="failed_count_nonnegative"
        ),
        sa.ForeignKeyConstraint(
            ["acquisition_source_id"], ["acquisition_sources.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_sync_runs"),
    )
    op.create_table(
        "sync_stream_state",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(36), nullable=False),
        sa.Column("acquisition_source_id", sa.String(36), nullable=True),
        sa.Column("stream_code", sa.String(160), nullable=False),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("watermark", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trailing_window_days", sa.Integer(), nullable=True),
        sa.Column("diagnostic_status", sa.String(100), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["acquisition_source_id"], ["acquisition_sources.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_sync_stream_state"),
        sa.UniqueConstraint(
            "provider_id",
            "acquisition_source_id",
            "stream_code",
            name="uq_sync_stream_state_identity",
        ),
    )
    op.create_index(
        "ux_sync_stream_state_without_source",
        "sync_stream_state",
        ["provider_id", "stream_code"],
        unique=True,
        sqlite_where=sa.text("acquisition_source_id IS NULL"),
    )
    op.create_index(
        "ux_sync_stream_state_with_source",
        "sync_stream_state",
        ["provider_id", "acquisition_source_id", "stream_code"],
        unique=True,
        sqlite_where=sa.text("acquisition_source_id IS NOT NULL"),
    )
    op.create_table(
        "coverage_intervals",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(36), nullable=False),
        sa.Column("acquisition_source_id", sa.String(36), nullable=True),
        sa.Column("stream_code", sa.String(160), nullable=False),
        sa.Column("metric_code", sa.String(120), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolution", sa.String(60), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("observed_count", sa.Integer(), nullable=True),
        sa.Column("expected_count", sa.Integer(), nullable=True),
        sa.Column("calculation_rule_version", sa.String(100), nullable=False),
        sa.Column("diagnostic_reason", sa.Text(), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('present', 'confirmed_empty', 'unavailable', 'failed', 'unknown')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "observed_count IS NULL OR observed_count >= 0", name="observed_count_nonnegative"
        ),
        sa.CheckConstraint(
            "expected_count IS NULL OR expected_count >= 0", name="expected_count_nonnegative"
        ),
        sa.CheckConstraint("interval_end > interval_start", name="interval_order"),
        sa.ForeignKeyConstraint(
            ["acquisition_source_id"], ["acquisition_sources.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_coverage_intervals"),
    )

    # Source evidence and derived values are append-only.  Corrections are
    # represented by a new row pointing to the superseded row.
    for table_name in (
        "raw_artifacts",
        "canonical_rule_sets",
        "measurement_sessions",
        "scalar_measurements",
        "derived_measurements",
        "canonical_selections",
        "import_candidate_edits",
    ):
        op.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS immutable_{table_name}_delete
            BEFORE DELETE ON {table_name}
            BEGIN
                SELECT RAISE(ABORT, '{table_name} are append-only');
            END
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS immutable_{table_name}_update
            BEFORE UPDATE ON {table_name}
            BEGIN
                SELECT RAISE(ABORT, '{table_name} are append-only');
            END
            """
        )

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
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS immutable_terminal_canonical_selection_runs_update
        BEFORE UPDATE ON canonical_selection_runs
        WHEN OLD.status <> 'running'
        BEGIN
            SELECT CASE WHEN
                NEW.scope_key IS NOT OLD.scope_key OR
                NEW.requested_start_date IS NOT OLD.requested_start_date OR
                NEW.requested_end_date IS NOT OLD.requested_end_date OR
                NEW.rule_set_id IS NOT OLD.rule_set_id OR
                NEW.rule_name IS NOT OLD.rule_name OR
                NEW.rule_version IS NOT OLD.rule_version OR
                NEW.rule_hash IS NOT OLD.rule_hash OR
                NEW.input_snapshot_hash IS NOT OLD.input_snapshot_hash OR
                NEW.scope_json IS NOT OLD.scope_json OR
                NEW.software_version IS NOT OLD.software_version OR
                NEW.build_version IS NOT OLD.build_version OR
                NEW.started_at IS NOT OLD.started_at OR
                NEW.completed_at IS NOT OLD.completed_at OR
                NEW.status IS NOT OLD.status OR
                NEW.selection_count IS NOT OLD.selection_count OR
                NEW.failure_reason IS NOT OLD.failure_reason OR
                NEW.supersedes_run_id IS NOT OLD.supersedes_run_id
            THEN RAISE(ABORT, 'terminal canonical selection runs are immutable') END;
        END
        """
    )


def downgrade() -> None:
    """Remove the first migration's tables for isolated test databases."""

    for table_name in (
        "raw_artifacts",
        "canonical_rule_sets",
        "measurement_sessions",
        "scalar_measurements",
        "derived_measurements",
        "canonical_selections",
        "import_candidate_edits",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS immutable_{table_name}_delete")
        op.execute(f"DROP TRIGGER IF EXISTS immutable_{table_name}_update")
    op.execute("DROP TRIGGER IF EXISTS immutable_terminal_import_candidates_update")
    op.execute("DROP TRIGGER IF EXISTS immutable_terminal_canonical_selection_runs_update")

    for index_name, table_name in (
        ("ux_sync_stream_state_with_source", "sync_stream_state"),
        ("ux_sync_stream_state_without_source", "sync_stream_state"),
        ("ux_canonical_successful_input", "canonical_selection_runs"),
        ("ux_scalar_measurements_import_candidate_metric", "scalar_measurements"),
        ("ux_scalar_measurements_single_successor", "scalar_measurements"),
        ("ix_scalar_measurements_metric_session", "scalar_measurements"),
        ("ux_measurement_sessions_confirmation_candidate", "measurement_sessions"),
        ("ux_measurement_sessions_single_successor", "measurement_sessions"),
        ("ux_measurement_sessions_source_fingerprint_revision", "measurement_sessions"),
        ("ux_measurement_sessions_source_record_revision", "measurement_sessions"),
        ("ux_measurement_sessions_semantic_revision", "measurement_sessions"),
        ("ix_measurement_sessions_source_identity", "measurement_sessions"),
        ("ux_ingest_events_deduplication_key", "ingest_events"),
        ("ux_acquisition_sources_natural_identity", "acquisition_sources"),
        ("ux_acquisition_sources_sender_instance_id", "acquisition_sources"),
    ):
        op.drop_index(index_name, table_name=table_name)

    for table_name in (
        "coverage_intervals",
        "sync_stream_state",
        "sync_runs",
        "canonical_selections",
        "canonical_selection_runs",
        "canonical_rule_sets",
        "derived_measurements",
        "scalar_measurements",
        "measurement_sessions",
        "import_candidate_edits",
        "import_candidates",
        "ingest_events",
        "ingest_batches",
        "raw_artifacts",
        "measurement_algorithms",
        "acquisition_sources",
        "physical_devices",
        "providers",
    ):
        op.drop_table(table_name)
