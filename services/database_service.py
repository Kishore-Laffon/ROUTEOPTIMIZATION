from supabase import create_client, Client
from models.db_models import DeliveryOrder, Vehicle, OptimizationResult
from datetime import datetime
import db_config

class DatabaseService:
    def __init__(self, supabase_url: str, supabase_key: str):
        """Initialize Supabase client"""
        self.supabase: Client = create_client(supabase_url, supabase_key)
    
    def get_orders_for_date(self, delivery_date):
        """Fetch all orders for a specific date from Supabase"""
        try:
            # Query Supabase
            response = self.supabase.table("delivery_orders").select("*").eq(
                "delivery_date", delivery_date.isoformat()
            ).execute()
            
            orders = []
            for row in response.data:
                order = DeliveryOrder()
                order.id = row['id']
                order.order_id = row['order_id']
                order.customer_name = row['customer_name']
                order.latitude = row['latitude']
                order.longitude = row['longitude']
                order.weight_kg = row['weight_kg']
                orders.append(order)
            return orders
        except Exception as e:
            print(f"Error fetching orders: {e}")
            return []
    
    def get_available_vehicles(self):
        """Fetch vehicles with available status from Supabase"""
        try:
            # Query Supabase
            response = self.supabase.table("vehicles").select("*").eq(
                "status", "AVAILABLE"
            ).execute()
            
            vehicles = []
            for row in response.data:
                vehicle = Vehicle()
                vehicle.id = row['id']
                vehicle.vehicle_code = row['vehicle_code']
                vehicle.capacity_kg = row['capacity_kg']
                vehicle.current_lat = row.get('current_lat', 0)
                vehicle.current_lng = row.get('current_lng', 0)
                vehicle.status = row['status']
                vehicles.append(vehicle)
            return vehicles
        except Exception as e:
            print(f"Error fetching vehicles: {e}")
            return []
    
    def save_optimization_result(self, job_id, result_data):
        """Save optimization result to Supabase"""
        try:
            response = self.supabase.table("optimization_results").insert({
                "job_id": job_id,
                "delivery_date": result_data.get('delivery_date', datetime.utcnow().isoformat()),
                "total_distance_km": result_data.get('total_distance_km', 0),
                "routes_count": result_data.get('routes_count', 0),
                "vehicles_used": result_data.get('vehicles_used', 0),
                "orders_routed": result_data.get('orders_routed', 0),
                "optimization_time_sec": result_data.get('opt_time', 0),
                "result_json": str(result_data)
            }).execute()
            print(f"✓ Optimization result saved: {job_id}")
            return response.data
        except Exception as e:
            print(f"Error saving result: {e}")
            return None

# Create singleton instance
_db_service = None

def get_database_service():
    """Get or create database service"""
    global _db_service
    if _db_service is None:
        _db_service = DatabaseService(db_config.SUPABASE_URL, db_config.SUPABASE_SERVICE_KEY)
    return _db_service
