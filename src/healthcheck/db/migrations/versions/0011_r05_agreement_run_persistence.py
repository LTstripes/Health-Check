"""Add immutable, versioned R05 agreement-run persistence.

Revision ID: 0011_r05_agreement_run_persistence
Revises: 0010_google_typed_normalization

This revision is additive.  It stores the frozen R05 projection/eligibility
snapshot and normalized child rows without altering either provider's source
tables.  Agreement rows are append-only; a run may transition once from
``running`` to a terminal state so construction can remain transactional.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_r05_agreement_run_persistence"
down_revision = "0010_google_typed_normalization"
branch_labels = None
depends_on = None


def _create_immutability_triggers() -> None:
    op.execute(
        """
        CREATE TRIGGER immutable_agreement_rule_sets_delete
        BEFORE DELETE ON agreement_rule_sets
        BEGIN
            SELECT RAISE(ABORT, 'agreement_rule_sets are append-only');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER immutable_agreement_rule_sets_update
        BEFORE UPDATE ON agreement_rule_sets
        BEGIN
            SELECT RAISE(ABORT, 'agreement_rule_sets are append-only');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER immutable_agreement_runs_delete
        BEFORE DELETE ON agreement_runs
        BEGIN
            SELECT RAISE(ABORT, 'agreement_runs are append-only');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER immutable_agreement_runs_terminal_update
        BEFORE UPDATE ON agreement_runs
        WHEN OLD.status <> 'running'
        BEGIN
            SELECT RAISE(ABORT, 'terminal agreement_runs are immutable');
        END
        """
    )
    for table_name in (
        "agreement_run_pairs",
        "agreement_run_exclusions",
        "agreement_metric_results",
        "agreement_coverages",
    ):
        op.execute(
            f"""
            CREATE TRIGGER immutable_{table_name}_delete
            BEFORE DELETE ON {table_name}
            BEGIN
                SELECT RAISE(ABORT, '{table_name} are append-only');
            END
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER immutable_{table_name}_update
            BEFORE UPDATE ON {table_name}
            BEGIN
                SELECT RAISE(ABORT, '{table_name} are append-only');
            END
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_insert_only_running
            BEFORE INSERT ON {table_name}
            WHEN COALESCE(
                (SELECT status FROM agreement_runs WHERE id = NEW.run_id), ''
            ) <> 'running'
            BEGIN
                SELECT RAISE(ABORT, '{table_name} require a running agreement run');
            END
            """
        )


def _drop_immutability_triggers() -> None:
    for trigger_name in (
        "immutable_agreement_rule_sets_delete",
        "immutable_agreement_rule_sets_update",
        "immutable_agreement_runs_delete",
        "immutable_agreement_runs_terminal_update",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
    for table_name in (
        "agreement_run_pairs",
        "agreement_run_exclusions",
        "agreement_metric_results",
        "agreement_coverages",
    ):
        for suffix in ("delete", "update", "insert_only_running"):
            op.execute(f"DROP TRIGGER IF EXISTS {table_name}_{suffix}")
        op.execute(f"DROP TRIGGER IF EXISTS immutable_{table_name}_delete")
        op.execute(f"DROP TRIGGER IF EXISTS immutable_{table_name}_update")


def upgrade() -> None:
    """Create the bounded R05 agreement snapshot and result tables."""

    op.create_table(
        "agreement_rule_sets",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("rule_name", sa.String(160), nullable=False),
        sa.Column("rule_version", sa.String(120), nullable=False),
        sa.Column("rule_definition_json", sa.Text(), nullable=False),
        sa.Column("rule_hash", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("length(rule_name) > 0", name="rule_name_nonempty"),
        sa.CheckConstraint("length(rule_version) > 0", name="rule_version_nonempty"),
        sa.CheckConstraint("length(rule_hash) >= 32", name="rule_hash_min_length"),
        sa.PrimaryKeyConstraint("id", name="pk_agreement_rule_sets"),
        sa.UniqueConstraint(
            "rule_name", "rule_version", name="uq_agreement_rule_sets_name_version"
        ),
    )

    op.create_table(
        "agreement_runs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("scope_key", sa.String(255), nullable=False),
        sa.Column("scope_lineage_key", sa.String(512), nullable=False),
        sa.Column("window_key", sa.String(255), nullable=False),
        sa.Column("requested_start_date", sa.Date(), nullable=True),
        sa.Column("requested_end_date", sa.Date(), nullable=True),
        sa.Column("cohort", sa.String(80), nullable=False),
        sa.Column("pairing_version", sa.String(120), nullable=False),
        sa.Column("metric_version", sa.String(120), nullable=False),
        sa.Column("statistic_version", sa.String(120), nullable=False),
        sa.Column("rule_set_id", sa.String(36), nullable=False),
        sa.Column("rule_name", sa.String(160), nullable=False),
        sa.Column("rule_version", sa.String(120), nullable=False),
        sa.Column("epoch_id", sa.String(160), nullable=False),
        sa.Column("epoch_basis_json", sa.Text(), nullable=False),
        sa.Column("input_snapshot_hash", sa.String(128), nullable=False),
        sa.Column("input_snapshot_json", sa.Text(), nullable=False),
        sa.Column("coverage_json", sa.Text(), nullable=False),
        sa.Column("identity_hash", sa.String(128), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'running'")),
        sa.Column("pair_count", sa.Integer(), nullable=True),
        sa.Column("exclusion_count", sa.Integer(), nullable=True),
        sa.Column("metric_count", sa.Integer(), nullable=True),
        sa.Column("coverage_count", sa.Integer(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("supersedes_run_id", sa.String(36), nullable=True),
        sa.CheckConstraint("status IN ('running', 'succeeded', 'failed')", name="status_allowed"),
        sa.CheckConstraint("length(scope_key) > 0", name="scope_key_nonempty"),
        sa.CheckConstraint("length(window_key) > 0", name="window_key_nonempty"),
        sa.CheckConstraint("length(cohort) > 0", name="cohort_nonempty"),
        sa.CheckConstraint("length(pairing_version) > 0", name="pairing_version_nonempty"),
        sa.CheckConstraint("length(metric_version) > 0", name="metric_version_nonempty"),
        sa.CheckConstraint("length(statistic_version) > 0", name="statistic_version_nonempty"),
        sa.CheckConstraint("length(rule_version) > 0", name="rule_version_nonempty"),
        sa.CheckConstraint("length(epoch_id) > 0", name="epoch_id_nonempty"),
        sa.CheckConstraint("length(input_snapshot_hash) >= 32", name="snapshot_hash_min_length"),
        sa.CheckConstraint("length(identity_hash) >= 32", name="identity_hash_min_length"),
        sa.CheckConstraint("pair_count IS NULL OR pair_count >= 0", name="pair_count_nonnegative"),
        sa.CheckConstraint(
            "exclusion_count IS NULL OR exclusion_count >= 0",
            name="exclusion_count_nonnegative",
        ),
        sa.CheckConstraint(
            "metric_count IS NULL OR metric_count >= 0", name="metric_count_nonnegative"
        ),
        sa.CheckConstraint(
            "coverage_count IS NULL OR coverage_count >= 0",
            name="coverage_count_nonnegative",
        ),
        sa.CheckConstraint(
            "(status = 'succeeded' AND completed_at IS NOT NULL AND failure_reason IS NULL) "
            "OR (status = 'failed' AND completed_at IS NOT NULL AND failure_reason IS NOT NULL) "
            "OR (status = 'running' AND completed_at IS NULL)",
            name="status_completion_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["rule_set_id"], ["agreement_rule_sets.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_run_id"], ["agreement_runs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agreement_runs"),
    )
    op.create_index(
        "ix_agreement_runs_scope_status",
        "agreement_runs",
        ["scope_lineage_key", "status", "completed_at"],
    )
    op.create_index("ix_agreement_runs_supersedes", "agreement_runs", ["supersedes_run_id"])
    op.create_index(
        "ux_agreement_runs_single_successor",
        "agreement_runs",
        ["supersedes_run_id"],
        unique=True,
        sqlite_where=sa.text("supersedes_run_id IS NOT NULL"),
    )
    op.create_index(
        "ux_agreement_runs_success_identity",
        "agreement_runs",
        ["identity_hash"],
        unique=True,
        sqlite_where=sa.text("status = 'succeeded'"),
    )
    op.create_index(
        "ux_agreement_runs_running_identity",
        "agreement_runs",
        ["identity_hash"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "agreement_run_pairs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("pair_key", sa.String(255), nullable=False),
        sa.Column("wake_date", sa.Date(), nullable=False),
        sa.Column("cohort", sa.String(80), nullable=False),
        sa.Column("source_class", sa.String(80), nullable=False),
        sa.Column("garmin_record_id", sa.String(36), nullable=False),
        sa.Column("google_record_id", sa.String(36), nullable=False),
        sa.Column("garmin_source_id", sa.String(36), nullable=False),
        sa.Column("google_source_id", sa.String(36), nullable=False),
        sa.Column("eligibility_json", sa.Text(), nullable=False),
        sa.Column("pair_json", sa.Text(), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        sa.CheckConstraint("length(pair_key) > 0", name="pair_key_nonempty"),
        sa.CheckConstraint("length(cohort) > 0", name="cohort_nonempty"),
        sa.ForeignKeyConstraint(["run_id"], ["agreement_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_agreement_run_pairs"),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_agreement_run_pairs_ordinal"),
        sa.UniqueConstraint("run_id", "pair_key", name="uq_agreement_run_pairs_key"),
    )
    op.create_index(
        "ix_agreement_run_pairs_wake_date",
        "agreement_run_pairs",
        ["run_id", "wake_date"],
    )

    op.create_table(
        "agreement_run_exclusions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("wake_date", sa.Date(), nullable=True),
        sa.Column("cohort", sa.String(80), nullable=True),
        sa.Column("reason", sa.String(160), nullable=False),
        sa.Column("garmin_record_ids_json", sa.Text(), nullable=False),
        sa.Column("google_record_ids_json", sa.Text(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("exclusion_json", sa.Text(), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        sa.CheckConstraint("length(reason) > 0", name="reason_nonempty"),
        sa.ForeignKeyConstraint(["run_id"], ["agreement_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_agreement_run_exclusions"),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_agreement_run_exclusions_ordinal"),
    )
    op.create_index(
        "ix_agreement_run_exclusions_wake_date",
        "agreement_run_exclusions",
        ["run_id", "wake_date"],
    )

    op.create_table(
        "agreement_metric_results",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("pair_id", sa.String(36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("metric_code", sa.String(160), nullable=False),
        sa.Column("variant", sa.String(80), nullable=True),
        sa.Column("variant_key", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("comparable", sa.Boolean(), nullable=False),
        sa.Column("difference_number", sa.Float(), nullable=True),
        sa.Column("difference_unit", sa.String(80), nullable=False),
        sa.Column("reason", sa.String(160), nullable=True),
        sa.Column("exclusion_basis", sa.String(200), nullable=True),
        sa.Column("garmin_json", sa.Text(), nullable=False),
        sa.Column("google_json", sa.Text(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("manifest_hash", sa.String(128), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        sa.CheckConstraint(
            "status IN ('comparable', 'unavailable', 'excluded')", name="status_allowed"
        ),
        sa.CheckConstraint("length(metric_code) > 0", name="metric_code_nonempty"),
        sa.CheckConstraint("length(variant_key) > 0", name="variant_key_nonempty"),
        sa.CheckConstraint("length(manifest_hash) >= 32", name="manifest_hash_min_length"),
        sa.ForeignKeyConstraint(["run_id"], ["agreement_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pair_id"], ["agreement_run_pairs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_agreement_metric_results"),
        sa.UniqueConstraint(
            "run_id", "pair_id", "metric_code", "variant_key",
            name="uq_agreement_metric_results_identity",
        ),
    )
    op.create_index(
        "ix_agreement_metric_results_run_metric",
        "agreement_metric_results",
        ["run_id", "metric_code", "variant_key"],
    )

    op.create_table(
        "agreement_coverages",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("metric_code", sa.String(160), nullable=False),
        sa.Column("variant", sa.String(80), nullable=True),
        sa.Column("variant_key", sa.String(80), nullable=False),
        sa.Column("comparable_count", sa.Integer(), nullable=False),
        sa.Column("unavailable_count", sa.Integer(), nullable=False),
        sa.Column("excluded_count", sa.Integer(), nullable=False),
        sa.Column("coverage_json", sa.Text(), nullable=False),
        sa.CheckConstraint("length(metric_code) > 0", name="metric_code_nonempty"),
        sa.CheckConstraint("length(variant_key) > 0", name="variant_key_nonempty"),
        sa.CheckConstraint("comparable_count >= 0", name="comparable_count_nonnegative"),
        sa.CheckConstraint("unavailable_count >= 0", name="unavailable_count_nonnegative"),
        sa.CheckConstraint("excluded_count >= 0", name="excluded_count_nonnegative"),
        sa.ForeignKeyConstraint(["run_id"], ["agreement_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_agreement_coverages"),
        sa.UniqueConstraint(
            "run_id", "metric_code", "variant_key", name="uq_agreement_coverages_identity"
        ),
    )
    _create_immutability_triggers()


def downgrade() -> None:
    """Remove only the additive R05 agreement persistence tables."""

    _drop_immutability_triggers()
    for table_name in (
        "agreement_coverages",
        "agreement_metric_results",
        "agreement_run_exclusions",
        "agreement_run_pairs",
        "agreement_runs",
        "agreement_rule_sets",
    ):
        op.drop_table(table_name)
