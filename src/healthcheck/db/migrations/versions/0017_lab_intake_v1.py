"""Local lab intake v1; frozen additive schema and append-only audit."""

from alembic import op

revision = "0017_lab_intake_v1"
down_revision = "0016_garmin_daily_summary_receipts"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """CREATE TABLE lab_reports (
    id VARCHAR(36) NOT NULL, 
    pdf_artifact_id VARCHAR(36) NOT NULL, 
    CONSTRAINT pk_lab_reports PRIMARY KEY (id), 
    CONSTRAINT uq_lab_reports_pdf_artifact_id UNIQUE (pdf_artifact_id), 
    CONSTRAINT fk_lab_reports_pdf_artifact_id_raw_artifacts
        FOREIGN KEY(pdf_artifact_id)
        REFERENCES raw_artifacts (id)
)
        """
    )
    op.execute(
        """CREATE TABLE lab_interpretations (
    id VARCHAR(36) NOT NULL, 
    report_id VARCHAR(36) NOT NULL, 
    draft_artifact_id VARCHAR(36) NOT NULL, 
    parent_id VARCHAR(36), 
    CONSTRAINT pk_lab_interpretations PRIMARY KEY (id), 
    CONSTRAINT uq_lab_interpretations_report_id UNIQUE (report_id, draft_artifact_id), 
    CONSTRAINT fk_lab_interpretations_report_id_lab_reports
        FOREIGN KEY(report_id)
        REFERENCES lab_reports (id), 
    CONSTRAINT fk_lab_interpretations_draft_artifact_id_raw_artifacts
        FOREIGN KEY(draft_artifact_id)
        REFERENCES raw_artifacts (id), 
    CONSTRAINT fk_lab_interpretations_parent_id_lab_interpretations
        FOREIGN KEY(parent_id)
        REFERENCES lab_interpretations (id)
)
        """
    )
    op.execute(
        """CREATE TABLE lab_revisions (
    id VARCHAR(36) NOT NULL, 
    report_id VARCHAR(36) NOT NULL, 
    interpretation_id VARCHAR(36) NOT NULL, 
    previous_id VARCHAR(36), 
    partial BOOLEAN NOT NULL, 
    snapshot_json TEXT NOT NULL, 
    CONSTRAINT pk_lab_revisions PRIMARY KEY (id), 
    CONSTRAINT uq_lab_revisions_report_id UNIQUE (report_id, id), 
    CONSTRAINT fk_lab_revisions_report_id_lab_reports
        FOREIGN KEY(report_id)
        REFERENCES lab_reports (id), 
    CONSTRAINT uq_lab_revisions_interpretation_id UNIQUE (interpretation_id), 
    CONSTRAINT fk_lab_revisions_interpretation_id_lab_interpretations
        FOREIGN KEY(interpretation_id)
        REFERENCES lab_interpretations (id), 
    CONSTRAINT fk_lab_revisions_previous_id_lab_revisions
        FOREIGN KEY(previous_id)
        REFERENCES lab_revisions (id)
)
        """
    )
    op.execute(
        """CREATE TABLE lab_heads (
    report_id VARCHAR(36) NOT NULL, 
    revision_id VARCHAR(36), 
    CONSTRAINT pk_lab_heads PRIMARY KEY (report_id), 
    CONSTRAINT fk_lab_heads_report_id_lab_reports
        FOREIGN KEY(report_id)
        REFERENCES lab_reports (id), 
    CONSTRAINT uq_lab_heads_revision_id UNIQUE (revision_id), 
    CONSTRAINT fk_lab_heads_revision_id_lab_revisions
        FOREIGN KEY(revision_id)
        REFERENCES lab_revisions (id)
)
        """
    )
    op.execute(
        """CREATE TABLE lab_results (
    revision_id VARCHAR(36) NOT NULL, 
    row_id VARCHAR(80) NOT NULL, 
    label_raw VARCHAR(255) NOT NULL, 
    result_raw TEXT NOT NULL, 
    unit_raw VARCHAR(255), 
    reference_raw TEXT, 
    value_kind VARCHAR(20) NOT NULL, 
    decimal VARCHAR(100), 
    comparator VARCHAR(2), 
    qualitative TEXT, 
    detail_json TEXT NOT NULL, 
    CONSTRAINT pk_lab_results PRIMARY KEY (revision_id, row_id), 
    CONSTRAINT ck_lab_results_kind_allowed
        CHECK (value_kind IN ('numeric','qualitative','unparsed')), 
    CONSTRAINT ck_lab_results_typed_value
        CHECK ((value_kind = 'numeric'
        AND decimal IS NOT NULL
        AND qualitative IS NULL)
        OR (value_kind != 'numeric'
        AND decimal IS NULL
        AND comparator IS NULL)), 
    CONSTRAINT fk_lab_results_revision_id_lab_revisions
        FOREIGN KEY(revision_id)
        REFERENCES lab_revisions (id)
)
        """
    )
    op.execute(
        """CREATE TABLE lab_operations (
    operation_id VARCHAR(80) NOT NULL, 
    fingerprint VARCHAR(64) NOT NULL, 
    receipt_json TEXT NOT NULL, 
    created_at DATETIME NOT NULL, 
    CONSTRAINT pk_lab_operations PRIMARY KEY (operation_id), 
    CONSTRAINT ck_lab_operations_fingerprint_sha256
        CHECK (length(fingerprint) = 64)
)
        """
    )
    op.execute(
        "CREATE TRIGGER immutable_lab_reports_update BEFORE UPDATE ON lab_reports BEGIN"
        " SELECT RAISE(ABORT, 'lab history is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER immutable_lab_reports_delete BEFORE DELETE ON lab_reports BEGIN"
        " SELECT RAISE(ABORT, 'lab history is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER immutable_lab_interpretations_update BEFORE UPDATE ON lab_inter"
        "pretations BEGIN SELECT RAISE(ABORT, 'lab history is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER immutable_lab_interpretations_delete BEFORE DELETE ON lab_inter"
        "pretations BEGIN SELECT RAISE(ABORT, 'lab history is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER immutable_lab_revisions_update BEFORE UPDATE ON lab_revisions B"
        "EGIN SELECT RAISE(ABORT, 'lab history is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER immutable_lab_revisions_delete BEFORE DELETE ON lab_revisions B"
        "EGIN SELECT RAISE(ABORT, 'lab history is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER immutable_lab_results_update BEFORE UPDATE ON lab_results BEGIN"
        " SELECT RAISE(ABORT, 'lab history is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER immutable_lab_results_delete BEFORE DELETE ON lab_results BEGIN"
        " SELECT RAISE(ABORT, 'lab history is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER immutable_lab_operations_update BEFORE UPDATE ON lab_operations"
        " BEGIN SELECT RAISE(ABORT, 'lab history is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER immutable_lab_operations_delete BEFORE DELETE ON lab_operations"
        " BEGIN SELECT RAISE(ABORT, 'lab history is append-only'); END"
    )


def downgrade():
    if op.get_bind().exec_driver_sql("SELECT 1 FROM lab_reports LIMIT 1").first():
        raise RuntimeError("lab intake downgrade refuses to discard staged or accepted history")
    op.drop_table("lab_operations")
    op.drop_table("lab_results")
    op.drop_table("lab_heads")
    op.drop_table("lab_revisions")
    op.drop_table("lab_interpretations")
    op.drop_table("lab_reports")
