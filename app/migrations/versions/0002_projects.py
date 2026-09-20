"""Projects: scope documents, agent runs, tasks and (optionally) API keys to a project.

A DATA migration, unlike the baseline. Existing rows have no project, so:
  1. create `projects` and a `default` project;
  2. add `project_id` to documents, agent_runs, tasks (and api_keys, nullable) and point every
     existing row at the default project, so a database that predates this keeps working unchanged;
  3. only then make the column NOT NULL and add the foreign keys and indexes;
  4. replace the global unique(sha256) with unique(project_id, sha256), so the same file can live in
     two projects.

Downgrade is refused if the same file exists in two projects (it would violate the old unique
constraint): merge or delete one first.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_DEFAULT = "(SELECT id FROM projects WHERE slug = 'default')"
_SCOPED = ("documents", "agent_runs", "tasks")  # NOT NULL after the backfill


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("slug", sa.String(40), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("slug"),
    )
    op.execute(
        "INSERT INTO projects (id, slug, name) VALUES (gen_random_uuid(), 'default', 'Default')"
    )

    for table in (*_SCOPED, "api_keys"):
        op.add_column(table, sa.Column("project_id", sa.Uuid(), nullable=True))
    for table in _SCOPED:  # every existing row belongs to the default project
        op.execute(f"UPDATE {table} SET project_id = {_DEFAULT}")  # noqa: S608 - fixed names
    for table in _SCOPED:
        op.alter_column(table, "project_id", nullable=False)
    for table in (*_SCOPED, "api_keys"):  # existing keys stay unscoped (NULL = every project)
        op.create_foreign_key(
            f"fk_{table}_project_id", table, "projects", ["project_id"], ["id"], ondelete="CASCADE"
        )
        op.create_index(f"ix_{table}_project_id", table, ["project_id"])

    op.drop_constraint("documents_sha256_key", "documents", type_="unique")
    op.create_unique_constraint(
        "uq_documents_project_sha256", "documents", ["project_id", "sha256"]
    )


def downgrade() -> None:
    duplicated = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM (SELECT sha256 FROM documents GROUP BY sha256 "
            "HAVING count(*) > 1) d"
        )
    )
    if duplicated.scalar():
        raise RuntimeError(
            "Cannot downgrade: the same file exists in more than one project, which the old "
            "schema forbids. Delete or merge the duplicates first."
        )
    op.drop_constraint("uq_documents_project_sha256", "documents", type_="unique")
    op.create_unique_constraint("documents_sha256_key", "documents", ["sha256"])
    for table in ("api_keys", *_SCOPED):
        op.drop_index(f"ix_{table}_project_id", table_name=table)
        op.drop_constraint(f"fk_{table}_project_id", table, type_="foreignkey")
        op.drop_column(table, "project_id")
    op.drop_table("projects")
