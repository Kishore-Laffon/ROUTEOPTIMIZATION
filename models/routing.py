# Teammate's models module - mock for testing
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum
from sqlalchemy.orm import declarative_base
from datetime import datetime, date
import enum

Base = declarative_base()

class Vehicle(Base):
    __tablename__ = "vehicles"
    
    id = Column(Integer, primary_key=True)
    depot_id = Column(Integer)
    vehicle_code = Column(String)
    status = Column(String, default="AVAILABLE")
    capacity_kg = Column(Float, default=5000)
    capacity_m3 = Column(Float, default=20)

class DeliveryOrder(Base):
    __tablename__ = "delivery_orders"
    
    id = Column(Integer, primary_key=True)
    depot_id = Column(Integer)
    delivery_date = Column(String)
    status = Column(String, default="PENDING")
    location_lat = Column(Float)
    location_lon = Column(Float)
    weight_kg = Column(Float)

class Route(Base):
    __tablename__ = "routes"
    
    id = Column(Integer, primary_key=True)
    job_id = Column(String)
    vehicle_id = Column(Integer)
    depot_id = Column(Integer)
    total_distance_km = Column(Float)
    total_duration_sec = Column(Integer)

class RouteStop(Base):
    __tablename__ = "route_stops"
    
    id = Column(Integer, primary_key=True)
    route_id = Column(Integer)
    order_id = Column(Integer)
    sequence = Column(Integer)
    arrival_time_sec = Column(Integer)

class VehicleLocation(Base):
    __tablename__ = "vehicle_locations"
    
    id = Column(Integer, primary_key=True)
    vehicle_id = Column(Integer)
    lat = Column(Float)
    lon = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)

class DisruptionEvent(Base):
    __tablename__ = "disruption_events"
    
    id = Column(Integer, primary_key=True)
    event_type = Column(String)
    description = Column(String)
    location_lat = Column(Float, nullable=True)
    location_lon = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

class Warehouse(Base):
    __tablename__ = "warehouses"
    
    id = Column(Integer, primary_key=True)
    name = Column(String)
    lat = Column(Float)
    lon = Column(Float)
