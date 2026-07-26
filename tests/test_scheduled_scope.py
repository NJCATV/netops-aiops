from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine

from aiops.scheduler.ai_scheduler import build_summary_config
from app.api.report_tasks import visible_task_query
from app.db import Base, make_session_factory
from app.models import ReportTask


def user(role_code: str, subject: str = "u-1", org_id: int | None = 7):
    identity = SimpleNamespace(role_code=role_code, subject=subject, org_id=org_id)
    return SimpleNamespace(platform_identity=identity)


def test_org_admin_sees_shared_task_catalogue():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        db.add_all(
            [
                ReportTask(name="org-7", scope_subject="u-1", scope_org_id=7, scope_regions_json=["jiangning"]),
                ReportTask(name="org-8", scope_subject="u-2", scope_org_id=8, scope_regions_json=["liuhe"]),
                ReportTask(name="global", scope_subject=None, scope_org_id=None, scope_regions_json=None),
            ]
        )
        db.commit()
        rows = db.execute(visible_task_query(user("org_admin"))).scalars().all()
    assert {row.name for row in rows} == {"org-7", "org-8", "global"}


def test_super_admin_sees_all_tasks():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        db.add_all([ReportTask(name="one", scope_org_id=7), ReportTask(name="global")])
        db.commit()
        rows = db.execute(visible_task_query(user("super_admin"))).scalars().all()
    assert {row.name for row in rows} == {"one", "global"}


def test_summary_builder_can_run_global_dataset():
    config = build_summary_config(24, None)
    assert config.allowed_device_ips is None
