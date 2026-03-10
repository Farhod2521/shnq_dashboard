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
