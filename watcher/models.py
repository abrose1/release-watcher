from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Date, Text, ForeignKey,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class TrackedCreator(Base):
    __tablename__ = "tracked_creators"

    id = Column(Integer, primary_key=True)
    category = Column(String, nullable=False)
    name = Column(String, nullable=False)
    tier = Column(Integer, nullable=False)
    external_id = Column(String, nullable=True)
    last_synced_from_profile = Column(DateTime, nullable=True)
    profile_score_at_sync = Column(Float, nullable=True)

    releases = relationship("Release", back_populates="tracked_creator")
    overrides = relationship("UserOverride", back_populates="tracked_creator")
    tier_changes = relationship("TierChange", back_populates="tracked_creator")


class Release(Base):
    __tablename__ = "releases"

    id = Column(Integer, primary_key=True)
    tracked_creator_id = Column(Integer, ForeignKey("tracked_creators.id"), nullable=True)
    external_release_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    type = Column(String, nullable=True)
    announced_date = Column(Date, nullable=True)
    release_date = Column(Date, nullable=True)
    notified_announced_at = Column(DateTime, nullable=True)
    notified_released_at = Column(DateTime, nullable=True)
    source_url = Column(String, nullable=True)
    announcement_hash = Column(String, nullable=True)

    tracked_creator = relationship("TrackedCreator", back_populates="releases")
    queue_items = relationship("NotificationQueue", back_populates="release")


class NotificationQueue(Base):
    __tablename__ = "notification_queue"

    id = Column(Integer, primary_key=True)
    release_id = Column(Integer, ForeignKey("releases.id"), nullable=True)
    discovery_sent_id = Column(Integer, ForeignKey("discovery_sent.id"), nullable=True)
    message_text = Column(Text, nullable=False)
    queued_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    send_after = Column(DateTime, nullable=False)
    priority = Column(Integer, nullable=False, default=50)
    sent_at = Column(DateTime, nullable=True)

    release = relationship("Release", back_populates="queue_items")
    discovery_sent = relationship("DiscoverySent", back_populates="queue_items")


class DiscoverySent(Base):
    __tablename__ = "discovery_sent"

    id = Column(Integer, primary_key=True)
    external_id = Column(String, nullable=False)
    category = Column(String, nullable=False)
    title = Column(String, nullable=False)
    creator_name = Column(String, nullable=False)
    sent_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    queue_items = relationship("NotificationQueue", back_populates="discovery_sent")


class UserOverride(Base):
    __tablename__ = "user_overrides"

    id = Column(Integer, primary_key=True)
    tracked_creator_id = Column(Integer, ForeignKey("tracked_creators.id"), nullable=True)
    action = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=True)

    tracked_creator = relationship("TrackedCreator", back_populates="overrides")


class TierChange(Base):
    __tablename__ = "tier_changes"

    id = Column(Integer, primary_key=True)
    tracked_creator_id = Column(Integer, ForeignKey("tracked_creators.id"), nullable=True)
    old_tier = Column(Integer, nullable=True)
    new_tier = Column(Integer, nullable=True)
    changed_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    tracked_creator = relationship("TrackedCreator", back_populates="tier_changes")
