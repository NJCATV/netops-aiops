"""Idempotently convert scheduled AIOps analysis tasks to global scope."""

from sqlalchemy import inspect, text

from app import create_app


def main() -> None:
    app = create_app()
    with app.app_context():
        session_factory = app.extensions["session_factory"]
        with session_factory() as session:
            column_names = {item["name"] for item in inspect(session.get_bind()).get_columns("report_tasks")}
            scope_columns = [name for name in ("scope_subject", "scope_org_name", "scope_regions_json") if name in column_names]
            assignments = ", ".join(f"{name} = NULL" for name in scope_columns)
            conditions = " OR ".join(f"{name} IS NOT NULL" for name in scope_columns)
            result = session.execute(text(f"UPDATE report_tasks SET {assignments} WHERE {conditions}")) if scope_columns else None
            session.commit()
            count = session.execute(text("SELECT COUNT(*) FROM report_tasks")).scalar_one()
            scoped = session.execute(text(f"SELECT COUNT(*) FROM report_tasks WHERE {conditions}")).scalar_one() if scope_columns else 0
            print(f"columns={scope_columns} updated={result.rowcount if result else 0} total={count} scoped={scoped}")


if __name__ == "__main__":
    main()
