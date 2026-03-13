import uuid

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def ensure_section_category_schema(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        return

    inspector = inspect(engine)
    if not inspector.has_table("categories"):
        return

    category_columns = {col["name"] for col in inspector.get_columns("categories")}
    if "section_id" in category_columns:
        return

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE categories ADD COLUMN section_id UUID"))

        default_section_id = str(uuid.uuid4())
        conn.execute(
            text(
                "INSERT INTO sections (id, code, name) "
                "VALUES (:id, :code, :name) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"id": default_section_id, "code": "UMUMIY", "name": "Umumiy"},
        )

        section_id = conn.execute(
            text("SELECT id FROM sections WHERE code = :code LIMIT 1"),
            {"code": "UMUMIY"},
        ).scalar_one()

        conn.execute(
            text("UPDATE categories SET section_id = :section_id WHERE section_id IS NULL"),
            {"section_id": section_id},
        )
        conn.execute(text("ALTER TABLE categories ALTER COLUMN section_id SET NOT NULL"))

        # Old schema `categories.code` unique constraintini olib tashlab,
        # yangi iyerarxik unique indexga o'tamiz.
        conn.execute(text("ALTER TABLE categories DROP CONSTRAINT IF EXISTS categories_code_key"))
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_section_category_code_idx "
                "ON categories (section_id, code)"
            )
        )


def ensure_qa_generator_schema(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        return

    inspector = inspect(engine)
    if not inspector.has_table("verified_qa"):
        return

    with engine.begin() as conn:
        statements = [
            "ALTER TABLE verified_qa ADD COLUMN IF NOT EXISTS document_id UUID",
            "ALTER TABLE verified_qa ADD COLUMN IF NOT EXISTS chapter_title VARCHAR(500)",
            "ALTER TABLE verified_qa ADD COLUMN IF NOT EXISTS clause_number VARCHAR(64)",
            "ALTER TABLE verified_qa ADD COLUMN IF NOT EXISTS has_table BOOLEAN DEFAULT FALSE",
            "ALTER TABLE verified_qa ADD COLUMN IF NOT EXISTS table_id UUID",
            "ALTER TABLE verified_qa ADD COLUMN IF NOT EXISTS table_number VARCHAR(64)",
            "ALTER TABLE verified_qa ADD COLUMN IF NOT EXISTS table_title VARCHAR(500)",
            "ALTER TABLE verified_qa ADD COLUMN IF NOT EXISTS lex_url TEXT",
            "ALTER TABLE verified_qa ADD COLUMN IF NOT EXISTS source_anchor VARCHAR(128)",
            "ALTER TABLE verified_qa ADD COLUMN IF NOT EXISTS source_excerpt TEXT",
            "ALTER TABLE verified_qa ADD COLUMN IF NOT EXISTS origin_type VARCHAR(32)",
            "ALTER TABLE verified_qa ADD COLUMN IF NOT EXISTS generation_job_id UUID",
        ]
        for statement in statements:
            conn.execute(text(statement))

        conn.execute(text("UPDATE verified_qa SET has_table = FALSE WHERE has_table IS NULL"))
        conn.execute(text("UPDATE verified_qa SET origin_type = 'feedback' WHERE origin_type IS NULL"))

        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_verified_qa_document_id "
                "ON verified_qa (document_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_verified_qa_clause_number "
                "ON verified_qa (clause_number)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_verified_qa_table_number "
                "ON verified_qa (table_number)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_verified_qa_origin_type "
                "ON verified_qa (origin_type)"
            )
        )
