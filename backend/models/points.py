"""Points: a student's allowance for starting lesson plans.

A teacher allots points to the students in their sections; starting a lesson
plan (Building Proficiency or Guided) costs a student BUILD_COST points, once
per plan. The plan is identified by the setup run's key, so leaving a plan and
coming back to it later never costs again. Teachers and admins don't pay.
"""
from datetime import datetime

from extensions import db, iso_utc

BUILD_COST = 30


class Build(db.Model):
    """One paid lesson plan: the student, the setup run it belongs to, and the
    plan it became once saved."""

    __tablename__ = "builds"
    __table_args__ = (db.UniqueConstraint("student_id", "run_key"),)

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    run_key = db.Column(db.String(64), nullable=False)
    points = db.Column(db.Integer, nullable=False, default=BUILD_COST)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {"id": self.id, "run_key": self.run_key, "points": self.points, "created_at": iso_utc(self.created_at)}


class PointEvent(db.Model):
    """Every change to a balance: a teacher's grant (or removal) or a build."""

    __tablename__ = "point_events"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    delta = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(20), nullable=False)  # "grant" | "build"
    by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    build_id = db.Column(db.Integer, db.ForeignKey("builds.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
