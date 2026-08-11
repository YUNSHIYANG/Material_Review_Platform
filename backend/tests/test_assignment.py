"""分配算法测试：双重排序、同团队规避、候选池不足、确定性兜底。"""
from app.assignment import assign_admin_review, assign_first_review, is_team_collision
from app.models import StaffReview, Submission, User

from conftest import make_submission, make_user


def _setup_staff_pool(db, n=4):
    return [make_user(db, "staff", real_name=f"审核员{i}", student_id=f"2024{i:03d}") for i in range(n)]


def test_assign_two_staff_and_counters(db):
    team = make_user(db, "team", real_name="财务部", member_names=["张三", "李四"], member_student_ids=["2024001", "2024002"])
    staffs = _setup_staff_pool(db)
    sub = make_submission(db, team)
    db.flush()
    tasks = assign_first_review(db, sub, team)
    db.commit()

    assert sub.status == "first_reviewing"
    reviews = db.query(StaffReview).filter_by(submission_id=sub.id).all()
    assert len(reviews) == 2
    for r in reviews:
        assert db.get(User, r.reviewer_id).current_pending_count == 1
    assert sub.first_assigned_at is not None
    assert tasks and tasks[0]["submission_id"] == sub.id


def test_collision_by_student_id(db):
    team = make_user(db, "team", real_name="财务部", member_names=["张三"], member_student_ids=["2024001"])
    staffs = _setup_staff_pool(db)
    staffs[0].student_id = "2024001"  # 命中团队学工号 → 排除
    db.flush()
    sub = make_submission(db, team)
    assign_first_review(db, sub, team)
    db.commit()
    reviewers = [r.reviewer_id for r in db.query(StaffReview).filter_by(submission_id=sub.id).all()]
    assert staffs[0].id not in reviewers


def test_collision_by_name_fallback(db):
    team = make_user(db, "team", real_name="财务部", member_names=["张三"], member_student_ids=["2024001"])
    staffs = _setup_staff_pool(db)
    staffs[1].student_id = None  # 无学工号 → 降级姓名匹配
    staffs[1].real_name = "张三"
    db.flush()
    sub = make_submission(db, team)
    assign_first_review(db, sub, team)
    db.commit()
    reviewers = [r.reviewer_id for r in db.query(StaffReview).filter_by(submission_id=sub.id).all()]
    assert staffs[1].id not in reviewers


def test_insufficient_staff_skips_to_admin(db):
    team = make_user(db, "team", real_name="财务部")
    make_user(db, "staff", real_name="仅一人", student_id="X1")
    make_user(db, "admin", real_name="管理员A", student_id="A1")
    make_user(db, "admin", real_name="管理员B", student_id="A2")
    sub = make_submission(db, team)
    db.flush()
    tasks = assign_first_review(db, sub, team)
    db.commit()
    assert sub.first_review_skip_reason == "insufficient_staff"
    assert sub.status == "admin_reviewing"
    assert sub.assigned_admin_id is not None
    assert any("初审候选池不足" in t.get("subject", "") for t in tasks)


def test_admin_pool_less_than_two_suspends(db):
    team = make_user(db, "team", real_name="财务部")
    make_user(db, "admin", real_name="唯一管理员", student_id="A1")
    sub = make_submission(db, team)
    db.flush()
    assign_admin_review(db, sub)
    db.commit()
    assert sub.status == "pending_admin_intervention"
    assert sub.assigned_admin_id is None


def test_load_balance_picks_idle_first(db):
    team = make_user(db, "team", real_name="财务部")
    busy = make_user(db, "staff", real_name="忙碌者", student_id="B1")
    idle = make_user(db, "staff", real_name="空闲者", student_id="I1")
    make_user(db, "staff", real_name="第三人", student_id="I2")
    busy.current_pending_count = 5
    sub = make_submission(db, team)
    db.flush()
    assign_first_review(db, sub, team)
    db.commit()
    reviewers = [r.reviewer_id for r in db.query(StaffReview).filter_by(submission_id=sub.id).all()]
    assert idle.id in reviewers
    assert busy.id not in reviewers


def test_deterministic_tie_break_min_id(db):
    team = make_user(db, "team", real_name="财务部")
    a = make_user(db, "staff", real_name="甲", student_id="S1")
    b = make_user(db, "staff", real_name="乙", student_id="S2")
    sub = make_submission(db, team)
    db.flush()
    assign_first_review(db, sub, team)
    db.commit()
    reviewers = sorted(r.reviewer_id for r in db.query(StaffReview).filter_by(submission_id=sub.id).all())
    assert reviewers == sorted([a.id, b.id])
