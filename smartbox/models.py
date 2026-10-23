from sqlalchemy import (Column, Integer, String, Float, DateTime, Boolean,
                        create_engine, MetaData, Table)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()

class SystemSettings(Base):
    __tablename__ = 'system_settings'
    id = Column(Integer, primary_key=True)
    cheap_hours_count = Column(Integer)
    temp_cheap = Column(Float)
    temp_expensive = Column(Float)
    indoor_max = Column(Float)
    indoor_min = Column(Float)
    friggebod_target = Column(Float)
    friggebod_frost = Column(Float)
    garage_target = Column(Float)
    garage_frost = Column(Float)
    radiator_solar_w = Column(Integer)
    spa_max_temp = Column(Float)
    spa_normal_temp = Column(Float)
    notify_spa_ready = Column(Boolean)
    notify_ev_start = Column(Boolean)
    notify_washer_start = Column(Boolean)
    spa_low_temp = Column(Float)
    spa_force_heat = Column(Boolean)
    spa_target_datetime = Column(DateTime)
    spa_target_temp = Column(Float)
    spa_schedule_enabled = Column(Boolean)
    legionella_temp = Column(Float)
    legionella_days = Column(Integer)
    water_target_normal = Column(Float)
    power_limit_kw = Column(Float)
    power_limit_kw_bas = Column(Float)
    power_limit_kw_hog = Column(Float)
    peak_shaving_enabled = Column(Boolean)
    ev_nissan_prio = Column(Integer)
    ev_tesla_prio = Column(Integer)
    away_mode_enabled = Column(Boolean)
    away_return_date = Column(DateTime)
    away_lights_on_return = Column(String)
    notify_spa_open = Column(Boolean)
    mower_mowing_threshold_w = Column(Float, default=3.2)
    mower_charging_threshold_w = Column(Float, default=10.0)
    fuse_size_a = Column(Float, default=25.0)

class Note(Base):
    __tablename__ = 'notes'
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    note_text = Column(String, nullable=False)

class Override(Base):
    __tablename__ = 'overrides'
    device = Column(String, primary_key=True)
    mode = Column(String)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class MowerActivity(Base):
    __tablename__ = 'mower_activity'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    power_w = Column(Float)
    energy_kwh = Column(Float)
    activity_label = Column(String)