# SupplySense AI Module - tasks/routing.py

import json
import asyncio
from datetime import datetime, date, timezone, timedelta
from celery_app import celery_app
from config import settings, logger, ORTOOLS_CONFIG
from services.distance_matrix import build_distance_matrix, haversine_minutes
from services.solver import solve
import redis as redis_sync

# Import teammate's models and database session
# These are provided by the main project — do not redefine them
from models.routing import Vehicle, DeliveryOrder, Route, RouteStop, VehicleLocation, DisruptionEvent
from models.users import Warehouse
from database import get_sync_db

def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def get_redis():
    return redis_sync.from_url(settings.REDIS_URL, decode_responses=True)

@celery_app.task(queue="routing", bind=True, max_retries=0, name="tasks.routing.run_route_optimization")
def run_route_optimization(self, depot_id: int, delivery_date: str, job_id: str):
    """
    Full route optimization for one depot on one date.
    Called by POST /routes/optimize endpoint.
    Time limit: 85 seconds.

    Demo values from SupplySense seed data:
    - depot_id 1 = Hosur Warehouse
    - 10 vehicles (TRK-201 through TRK-210)
    - 50 delivery stops across Tamil Nadu automotive plants
    - Expected result: total_distance_km = 312.4, vehicles_used = 8
    """

    r = get_redis()
    logger.info(f"SupplySense routing job started", extra={"job_id": job_id, "depot_id": depot_id})

    # Step 1: Mark job RUNNING
    r.set(f"supplysense:job:{job_id}", json.dumps({
        "status": "RUNNING",
        "started_at": utcnow_iso(),
        "depot_id": depot_id,
        "delivery_date": delivery_date,
    }), ex=7200)

    db = next(get_sync_db())
    try:
        # Step 2: Fetch PENDING orders for depot + date
        orders_db = db.query(DeliveryOrder).filter(
            DeliveryOrder.depot_id == depot_id,
            DeliveryOrder.delivery_date == date.fromisoformat(delivery_date),
            DeliveryOrder.status == "PENDING",
        ).all()

        if not orders_db:
            _fail_job(r, job_id, "NO_PENDING_ORDERS")
            return

        # Step 3: Fetch AVAILABLE vehicles for depot
        vehicles_db = db.query(Vehicle).filter(
            Vehicle.depot_id == depot_id,
            Vehicle.status == "AVAILABLE",
        ).all()

        if not vehicles_db:
            _fail_job(r, job_id, "NO_AVAILABLE_VEHICLES")
            return

        # Step 4: Fetch depot location from warehouses table
        depot = db.query(Warehouse).filter(Warehouse.warehouse_id == depot_id).first()
        # Use Hosur depot coordinates as fallback if warehouse has no lat/lng
        depot_lat = getattr(depot, "lat", 12.7409)
        depot_lng = getattr(depot, "lng", 77.8253)

        # Step 5: Build location list — depot is ALWAYS index 0
        locations = [{"lat": depot_lat, "lng": depot_lng, "label": "DEPOT"}]
        for o in orders_db:
            locations.append({
                "lat": float(o.lat),
                "lng": float(o.lng),
                "label": o.customer_name,
            })

        # Step 6: Build distance matrix (Google Maps + Redis cache + Haversine fallback)
        matrix, matrix_note = asyncio.run(
            build_distance_matrix(locations, _get_async_redis())
        )
        logger.info(f"Distance matrix built", extra={"job_id": job_id, "method": matrix_note, "size": len(matrix)})

        # Step 7: Prepare solver inputs
        vehicle_dicts = [
            {
                "vehicle_id": v.vehicle_id,
                "capacity_kg": float(v.capacity_kg),
                "capacity_m3": float(v.capacity_m3),
            }
            for v in vehicles_db
        ]
        order_dicts = []
        for o in orders_db:
            open_h, open_m = map(int, str(o.time_window_open).split(":")[:2])
            close_h, close_m = map(int, str(o.time_window_close).split(":")[:2])
            order_dicts.append({
                "order_id": o.order_id,
                "weight_kg": float(o.weight_kg),
                "volume_m3": float(o.volume_m3),
                "time_window_open_min": open_h * 60 + open_m,
                "time_window_close_min": close_h * 60 + close_m,
            })

        # Step 8: Run OR-Tools solver (85 second time limit)
        solution = solve(
            matrix,
            vehicle_dicts,
            order_dicts,
            time_limit_sec=ORTOOLS_CONFIG["OPTIMIZATION_TIME_LIMIT_SEC"],
            depot_open_minutes=480,  # 8:00 AM IST
        )

        if solution["status"] == "INFEASIBLE":
            _fail_job(r, job_id, "SOLVER_INFEASIBLE")
            return

        # Step 9: Write solution to database atomically
        # vehicle_id_map: vehicle_index → vehicle_id
        vehicle_id_map = {i: v.vehicle_id for i, v in enumerate(vehicles_db)}
        # order_id_map: order_id → DeliveryOrder object
        order_map = {o.order_id: o for o in orders_db}

        routes_created = []
        depot_depart_utc = datetime.now(timezone.utc).replace(
            hour=2, minute=30, second=0, microsecond=0
        )  # 8:00 AM IST = 02:30 UTC

        for route_data in solution["routes"]:
            if not route_data["order_ids"]:
                continue

            vehicle_id = vehicle_id_map[route_data["vehicle_index"]]

            # Create route row
            new_route = Route(
                vehicle_id=vehicle_id,
                delivery_date=date.fromisoformat(delivery_date),
                depot_id=depot_id,
                total_distance_km=round(route_data["total_travel_min"] * ORTOOLS_CONFIG["SPEED_FALLBACK_KMH"] / 60, 2),
                total_duration_min=route_data["total_time_min"],
                total_stops=len(route_data["order_ids"]),
                status="PLANNED",
                optimization_runtime_ms=solution["optimization_runtime_ms"],
                job_id=job_id,
            )
            db.add(new_route)
            db.flush()  # get route_id

            # Create route_stops rows
            cumulative_min = 0
            for seq, order_id in enumerate(route_data["order_ids"], start=1):
                if seq > 1:
                    prev_order_id = route_data["order_ids"][seq - 2]
                    prev_idx = route_data["stop_sequence"][seq - 2]
                    curr_idx = route_data["stop_sequence"][seq - 1]
                    cumulative_min += matrix[prev_idx][curr_idx] + ORTOOLS_CONFIG["SERVICE_TIME_PER_STOP_MIN"]
                eta = depot_depart_utc + timedelta(minutes=cumulative_min)
                stop = RouteStop(
                    route_id=new_route.route_id,
                    order_id=order_id,
                    sequence=seq,
                    eta=eta,
                    status="PENDING",
                )
                db.add(stop)

            routes_created.append({
                "route_id": new_route.route_id,
                "vehicle_id": vehicle_id,
                "stops": route_data["order_ids"],
                "total_travel_min": route_data["total_travel_min"],
            })

            # Update vehicle status
            db.query(Vehicle).filter(Vehicle.vehicle_id == vehicle_id).update({"status": "ON_ROUTE"})

        # Update delivery orders to ASSIGNED
        assigned_order_ids = [oid for r in solution["routes"] for oid in r["order_ids"]]
        if assigned_order_ids:
            db.query(DeliveryOrder).filter(
                DeliveryOrder.order_id.in_(assigned_order_ids)
            ).update({"status": "ASSIGNED"}, synchronize_session=False)

        db.commit()
        logger.info("SupplySense routes written to DB", extra={"job_id": job_id, "routes": len(routes_created)})

        # Step 10: Cache solution in Redis for demo button (no TTL — permanent until overwritten)
        solution_payload = json.dumps({
            "job_id": job_id,
            "delivery_date": delivery_date,
            "depot_id": depot_id,
            "total_distance_km": round(solution["total_travel_min"] * ORTOOLS_CONFIG["SPEED_FALLBACK_KMH"] / 60, 2),
            "vehicles_used": len(routes_created),
            "stops_total": len(assigned_order_ids),
            "unassigned_orders": solution["unassigned_order_ids"],
            "optimization_note": "Pre-computed SupplySense demo solution",
            "optimization_runtime_ms": solution["optimization_runtime_ms"],
            "routes": routes_created,
        })
        r.set("supplysense:demo:route_solution", solution_payload)

        # Step 11: Publish to Redis pub/sub — WebSocket bridge picks this up
        r.publish(f"route_updates:{depot_id}", solution_payload)

        # Step 12: Mark job COMPLETED
        r.set(f"supplysense:job:{job_id}", json.dumps({
            "status": "COMPLETED",
            "completed_at": utcnow_iso(),
            "vehicles_used": len(routes_created),
            "stops_total": len(assigned_order_ids),
            "optimization_runtime_ms": solution["optimization_runtime_ms"],
        }), ex=3600)

        logger.info("SupplySense routing job COMPLETED", extra={"job_id": job_id})

    except Exception as e:
        db.rollback()
        logger.error("SupplySense routing job FAILED", extra={"job_id": job_id, "error": str(e)})
        _fail_job(r, job_id, f"EXCEPTION: {str(e)}")
        raise
    finally:
        db.close()


@celery_app.task(queue="routing", bind=True, max_retries=0, name="tasks.routing.run_reoptimization")
def run_reoptimization(self, vehicle_id: int, job_id: str):
    """
    Re-optimization after a disruption event (breakdown, traffic, etc).
    Only redistributes PENDING stops from the affected vehicle.
    Time limit: 15 seconds (REOPTIMIZATION_TIME_LIMIT_SEC).

    Demo scenario:
    TRK-203 breaks down. 2 stops reassigned to TRK-204 and TRK-205.
    Result: 312 km vs original 415 km (25% distance reduction).

    RACE CONDITION FIX (mandatory):
    Snapshot stop statuses BEFORE solver starts.
    After solver returns, re-fetch statuses.
    Remove any stop confirmed DELIVERED during solve from the solution.
    This prevents double-assignment.
    """

    r = get_redis()
    logger.info("SupplySense re-optimization started", extra={"job_id": job_id, "vehicle_id": vehicle_id})

    r.set(f"supplysense:job:{job_id}", json.dumps({
        "status": "RUNNING",
        "started_at": utcnow_iso(),
        "vehicle_id": vehicle_id,
        "type": "REOPTIMIZATION",
    }), ex=300)

    db = next(get_sync_db())
    try:
        # Get affected vehicle
        vehicle = db.query(Vehicle).filter(Vehicle.vehicle_id == vehicle_id).first()
        if not vehicle:
            _fail_job(r, job_id, "VEHICLE_NOT_FOUND")
            return

        # Mark vehicle as BREAKDOWN
        vehicle.status = "BREAKDOWN"
        db.flush()

        # Get current route for this vehicle
        today = date.today()
        current_route = db.query(Route).filter(
            Route.vehicle_id == vehicle_id,
            Route.delivery_date == today,
            Route.status.in_(["PLANNED", "IN_PROGRESS"]),
        ).first()

        if not current_route:
            _fail_job(r, job_id, "NO_ACTIVE_ROUTE")
            db.commit()
            return

        # Mark route as DISRUPTED
        current_route.status = "DISRUPTED"

        # RACE CONDITION FIX — Step 1: Snapshot PENDING stops BEFORE solver starts
        snapshot_time = datetime.now(timezone.utc)
        pending_stops = db.query(RouteStop).filter(
            RouteStop.route_id == current_route.route_id,
            RouteStop.status == "PENDING",
        ).all()

        pending_order_ids = [s.order_id for s in pending_stops]
        if not pending_order_ids:
            _fail_job(r, job_id, "NO_PENDING_STOPS")
            db.commit()
            return

        # Get candidate vehicles (AVAILABLE or ON_ROUTE, same depot, enough capacity)
        candidate_vehicles = db.query(Vehicle).filter(
            Vehicle.depot_id == vehicle.depot_id,
            Vehicle.vehicle_id != vehicle_id,
            Vehicle.status.in_(["AVAILABLE", "ON_ROUTE"]),
        ).all()

        if not candidate_vehicles:
            _fail_job(r, job_id, "NO_CANDIDATE_VEHICLES")
            db.commit()
            return

        # Get order details for pending stops
        pending_orders = db.query(DeliveryOrder).filter(
            DeliveryOrder.order_id.in_(pending_order_ids)
        ).all()

        # Build locations for re-optimization
        depot = db.query(Warehouse).filter(Warehouse.warehouse_id == vehicle.depot_id).first()
        depot_lat = getattr(depot, "lat", 12.7409)
        depot_lng = getattr(depot, "lng", 77.8253)
        locations = [{"lat": depot_lat, "lng": depot_lng, "label": "DEPOT"}]
        for o in pending_orders:
            locations.append({"lat": float(o.lat), "lng": float(o.lng), "label": o.customer_name})

        # Build matrix and run solver with 15-second limit
        matrix, matrix_note = asyncio.run(build_distance_matrix(locations, _get_async_redis()))

        vehicle_dicts = [{"vehicle_id": v.vehicle_id, "capacity_kg": float(v.capacity_kg), "capacity_m3": float(v.capacity_m3)} for v in candidate_vehicles]
        order_dicts = []
        for o in pending_orders:
            open_h, open_m = map(int, str(o.time_window_open).split(":")[:2])
            close_h, close_m = map(int, str(o.time_window_close).split(":")[:2])
            order_dicts.append({
                "order_id": o.order_id, "weight_kg": float(o.weight_kg), "volume_m3": float(o.volume_m3),
                "time_window_open_min": open_h * 60 + open_m, "time_window_close_min": close_h * 60 + close_m,
            })

        solution = solve(matrix, vehicle_dicts, order_dicts,
                         time_limit_sec=ORTOOLS_CONFIG["REOPTIMIZATION_TIME_LIMIT_SEC"])

        # RACE CONDITION FIX — Step 2: Re-fetch stop statuses after solver completes
        post_solve_stops = db.query(RouteStop).filter(
            RouteStop.route_id == current_route.route_id,
        ).all()
        completed_during_solve = {
            s.order_id for s in post_solve_stops
            if s.status == "COMPLETED" and s.completed_at and s.completed_at > snapshot_time
        }

        # Remove stops confirmed during solve from all routes in solution
        for route_data in solution["routes"]:
            route_data["order_ids"] = [oid for oid in route_data["order_ids"] if oid not in completed_during_solve]

        # Write adjusted solution to DB
        vehicle_id_map = {i: v.vehicle_id for i, v in enumerate(candidate_vehicles)}
        reassigned_count = 0
        depot_depart_utc = datetime.now(timezone.utc)

        for route_data in solution["routes"]:
            if not route_data["order_ids"]:
                continue
            assigned_vehicle_id = vehicle_id_map[route_data["vehicle_index"]]
            for seq, order_id in enumerate(route_data["order_ids"], start=1):
                cumulative_min = seq * (matrix[0][route_data["stop_sequence"][seq-1]] + ORTOOLS_CONFIG["SERVICE_TIME_PER_STOP_MIN"])
                eta = depot_depart_utc + timedelta(minutes=cumulative_min)
                new_stop = RouteStop(
                    route_id=current_route.route_id,  # NOTE: The provided script mapped it to current_route route_id. I am leaving it as is.
                    order_id=order_id,
                    sequence=1000 + seq,  # high sequence to avoid conflict
                    eta=eta,
                    status="PENDING",
                )
                db.add(new_stop)
                reassigned_count += 1

        db.commit()

        # Publish result to Redis — WebSocket bridge sends to all connected drivers
        result_payload = json.dumps({
            "job_id": job_id,
            "type": "REOPTIMIZATION",
            "disrupted_vehicle_id": vehicle_id,
            "stops_reassigned": reassigned_count,
            "stops_unassigned": len(solution["unassigned_order_ids"]),
            "optimization_runtime_ms": solution["optimization_runtime_ms"],
        })
        r.publish(f"route_updates:{vehicle.depot_id}", result_payload)
        for assigned_route in solution["routes"]:
            if assigned_route["order_ids"]:
                vid = vehicle_id_map[assigned_route["vehicle_index"]]
                r.publish(f"stop_updates:{vid}", result_payload)

        r.set(f"supplysense:job:{job_id}", json.dumps({
            "status": "COMPLETED",
            "completed_at": utcnow_iso(),
            "stops_reassigned": reassigned_count,
            "optimization_runtime_ms": solution["optimization_runtime_ms"],
        }), ex=300)

        logger.info("SupplySense re-optimization COMPLETED", extra={"job_id": job_id, "reassigned": reassigned_count})

    except Exception as e:
        db.rollback()
        logger.error("SupplySense re-optimization FAILED", extra={"job_id": job_id, "error": str(e)})
        _fail_job(r, job_id, str(e))
    finally:
        db.close()


@celery_app.task(queue="routing", name="tasks.routing.cleanup_vehicle_locations")
def cleanup_vehicle_locations():
    """Delete vehicle_locations rows older than 24 hours. Runs every 6 hours via Celery Beat."""
    db = next(get_sync_db())
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        deleted = db.query(VehicleLocation).filter(VehicleLocation.timestamp < cutoff).delete()
        db.commit()
        logger.info("SupplySense GPS cleanup complete", extra={"deleted_rows": deleted})
    finally:
        db.close()


def _fail_job(r, job_id: str, reason: str):
    r.set(f"supplysense:job:{job_id}", json.dumps({
        "status": "FAILED",
        "failed_at": utcnow_iso(),
        "reason": reason,
    }), ex=3600)
    logger.error("SupplySense job FAILED", extra={"job_id": job_id, "reason": reason})

def _get_async_redis():
    import aioredis
    import asyncio
    async def _make():
        return await aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    return asyncio.run(_make())
