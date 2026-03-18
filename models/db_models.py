from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class DeliveryOrder(Base):
    """Real delivery orders from Supabase"""
    __tablename__ = "delivery_orders"
    
    id = Column(Integer, primary_key=True)
    order_id = Column(String(50), unique=True)
    customer_name = Column(String(100))
    latitude = Column(Float)
    longitude = Column(Float)
    weight_kg = Column(Float)
    delivery_date = Column(DateTime)
    time_window_start = Column(String(5))  # HH:MM format
    time_window_end = Column(String(5))    # HH:MM format
    created_at = Column(DateTime, default=datetime.utcnow)

class Vehicle(Base):
    """Vehicles available for delivery"""
    __tablename__ = "vehicles"
    
    id = Column(Integer, primary_key=True)
    vehicle_code = Column(String(20), unique=True)
    capacity_kg = Column(Float)
    current_lat = Column(Float, default=0)
    current_lng = Column(Float, default=0)
    status = Column(String(20), default="AVAILABLE")
    created_at = Column(DateTime, default=datetime.utcnow)

class OptimizationResult(Base):
    """Store optimization results"""
    __tablename__ = "optimization_results"
    
    id = Column(Integer, primary_key=True)
    job_id = Column(String(50), unique=True)
    delivery_date = Column(DateTime)
    total_distance_km = Column(Float)
    routes_count = Column(Integer)
    vehicles_used = Column(Integer)
    orders_routed = Column(Integer)
    optimization_time_sec = Column(Float)
    result_json = Column(String(5000))  # Store full result as JSON
    created_at = Column(DateTime, default=datetime.utcnow)
