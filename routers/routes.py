# SupplySense AI Module - routers/routes.py

import json
import uuid
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Header, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel
from typing import Optional
import redis
from config import settings, logger
from tasks.routing import run_route_optimization, run_reoptimization
from websocket.bridge import manager

# Import teammate's auth
from auth.dependencies import get_current_user, verify_internal_key, require_roles

router = APIRouter(prefix="/routes", tags=["SupplySense Routing"])

class OptimizeRequest(BaseModel):
    depot_id: int
    delivery_date: date

class DisruptionRequest(BaseModel):
    event_type: str   # VEHICLE_BREAKDOWN | TRAFFIC_CONGESTION | DELIVERY_FAILED | WEATHER_ALERT
    description: Optional[str] = None
    location: Optional[dict] = None   # {"lat": float, "lng": float}

class GPSPingRequest(BaseModel):
    vehicle_id: int
    timestamp: datetime
    lat: float
    lng: float


@router.post("/optimize", status_code=202)
async def optimize_routes(
    body: OptimizeRequest,
    current_user: dict = Depends(require_roles("dispatch_manager", "operations_manager")),
):
    """
    Enqueue route optimization for one depot on one date.
    Returns immediately with job_id. Never waits for OR-Tools.
    Poll GET /routes/jobs/{job_id} for status.

    Demo: POST {"depot_id": 1, "delivery_date": "2026-03-14"}
    Expected: 50 stops, 8 vehicles used, total_distance_km = 312.4
    """
    # Import teammate's models for validation query
    from models.routing import DeliveryOrder, Vehicle
    from database import AsyncSessionLocal
    from sqlalchemy import select, func

    async with AsyncSessionLocal() as db:
        order_count_result = await db.execute(
            select(func.count()).where(
                DeliveryOrder.depot_id == body.depot_id,
                DeliveryOrder.delivery_date == body.delivery_date,
                DeliveryOrder.status == "PENDING",
            )
        )
        order_count = order_count_result.scalar()

        vehicle_count_result = await db.execute(
            select(func.count()).where(
                Vehicle.depot_id == body.depot_id,
                Vehicle.status == "AVAILABLE",
            )
        )
        vehicle_count = vehicle_count_result.scalar()

    if order_count == 0:
        raise HTTPException(400, detail={"error": "NO_PENDING_ORDERS",
            "message": f"No PENDING delivery orders found for depot {body.depot_id} on {body.delivery_date}"})

    if vehicle_count == 0:
        raise HTTPException(400, detail={"error": "NO_AVAILABLE_VEHICLES",
            "message": f"No AVAILABLE vehicles found for depot {body.depot_id}"})

    job_id = f"JOB-{body.delivery_date}-{uuid.uuid4().hex[:6].upper()}"

    # Set initial job state in Redis
    r = redis.from_url(settings.REDIS_URL, decode_responses=True)
    r.set(f"supplysense:job:{job_id}", json.dumps({
        "status": "QUEUED",
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "depot_id": body.depot_id,
        "delivery_date": str(body.delivery_date),
    }), ex=7200)
    r.close()

    # Enqueue to Celery routing queue
    run_route_optimization.apply_async(
        args=[body.depot_id, str(body.delivery_date), job_id],
        queue="routing",
    )

    logger.info("SupplySense optimization queued", extra={"job_id": job_id, "user_id": current_user["user_id"]})

    return {
        "job_id": job_id,
        "status": "QUEUED",
        "pending_orders": order_count,
        "available_vehicles": vehicle_count,
        "estimated_completion_sec": 90,
        "poll_url": f"/routes/jobs/{job_id}",
        "message": "SupplySense optimization queued. Poll poll_url for status.",
    }


@router.get("/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    current_user: dict = Depends(require_roles("dispatch_manager", "operations_manager")),
):
    """Poll optimization job status. Returns QUEUED | RUNNING | COMPLETED | FAILED."""
    r = redis.from_url(settings.REDIS_URL, decode_responses=True)
    raw = r.get(f"supplysense:job:{job_id}")
    r.close()

    if not raw:
        raise HTTPException(404, detail={"error": "JOB_NOT_FOUND", "message": f"No job found with ID {job_id}"})

    job_data = json.loads(raw)

    # Calculate elapsed seconds if started_at exists
    if "started_at" in job_data:
        started = datetime.fromisoformat(job_data["started_at"])
        elapsed = int((datetime.now(timezone.utc) - started).total_seconds())
        job_data["elapsed_sec"] = elapsed

    return job_data


@router.get("/demo/solution")
async def get_demo_solution(
    current_user: dict = Depends(require_roles("dispatch_manager", "operations_manager")),
):
    """
    Return pre-cached SupplySense demo route solution. Always returns instantly.
    Never triggers OR-Tools.

    This endpoint exists because OR-Tools uses ~400 MB RAM on Railway 512 MB free tier.
    Running live during demo risks OOM kill. Pre-compute night before using POST /routes/optimize.
    The demo "Optimize Routes" button calls THIS endpoint — not /optimize.

    Pre-compute command (run night before demo):
        POST /routes/optimize {"depot_id": 1, "delivery_date": "2026-03-14"}
        Wait for COMPLETED. Verify this endpoint returns 200 with total_distance_km = 312.4
    """
    r = redis.from_url(settings.REDIS_URL, decode_responses=True)
    cached = r.get("supplysense:demo:route_solution")
    r.close()

    if not cached:
        raise HTTPException(503, detail={
            "error": "DEMO_SOLUTION_NOT_CACHED",
            "message": "SupplySense demo solution not found. Run POST /routes/optimize before the demo and wait for COMPLETED status.",
        })

    return json.loads(cached)


@router.post("/vehicles/{vehicle_id}/disruption", status_code=202)
async def report_disruption(
    vehicle_id: int,
    body: DisruptionRequest,
    current_user: dict = Depends(require_roles("dispatch_manager", "operations_manager")),
):
    """
    Report a vehicle disruption. Triggers re-optimization of pending stops.
    Time limit: 15 seconds. Returns immediately with reopt_job_id.

    Demo scenario:
    POST /routes/vehicles/3/disruption
    {"event_type": "VEHICLE_BREAKDOWN", "description": "Engine failure near Perungudi"}
    Result: TRK-203 stops reassigned to TRK-204 and TRK-205 in under 15 seconds.
    """
    allowed_types = ["VEHICLE_BREAKDOWN", "TRAFFIC_CONGESTION", "DELIVERY_FAILED", "WEATHER_ALERT"]
    if body.event_type not in allowed_types:
        raise HTTPException(400, detail={"error": "INVALID_EVENT_TYPE",
            "message": f"event_type must be one of: {', '.join(allowed_types)}"})

    from models.routing import Vehicle, RouteStop, Route, DisruptionEvent
    from database import AsyncSessionLocal
    from sqlalchemy import select, func

    async with AsyncSessionLocal() as db:
        vehicle = await db.get(Vehicle, vehicle_id)
        if not vehicle:
            raise HTTPException(404, detail={"error": "VEHICLE_NOT_FOUND",
                "message": f"No vehicle found with ID {vehicle_id}"})

        if vehicle.status != "ON_ROUTE":
            raise HTTPException(400, detail={"error": "VEHICLE_NOT_ON_ROUTE",
                "message": f"Vehicle {vehicle.vehicle_code} is not ON_ROUTE — cannot report disruption"})

        # Count pending stops
        today = date.today()
        route_result = await db.execute(
            select(Route).where(Route.vehicle_id == vehicle_id, Route.delivery_date == today, Route.status.in_(["PLANNED", "IN_PROGRESS"]))
        )
        current_route = route_result.scalar_one_or_none()
        pending_count = 0
        if current_route:
            count_result = await db.execute(
                select(func.count()).where(RouteStop.route_id == current_route.route_id, RouteStop.status == "PENDING")
            )
            pending_count = count_result.scalar()

        # Log disruption event
        disruption = DisruptionEvent(
            vehicle_id=vehicle_id,
            route_id=current_route.route_id if current_route else None,
            event_type=body.event_type,
            description=body.description,
            lat=body.location.get("lat") if body.location else None,
            lng=body.location.get("lng") if body.location else None,
            stops_affected=pending_count,
            status="DETECTED",
        )
        db.add(disruption)
        await db.commit()
        await db.refresh(disruption)

    reopt_job_id = f"JOB-REOPT-{vehicle_id}-{uuid.uuid4().hex[:6].upper()}"

    r = redis.from_url(settings.REDIS_URL, decode_responses=True)
    r.set(f"supplysense:job:{reopt_job_id}", json.dumps({
        "status": "QUEUED",
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "type": "REOPTIMIZATION",
        "vehicle_id": vehicle_id,
    }), ex=300)
    r.close()

    run_reoptimization.apply_async(args=[vehicle_id, reopt_job_id], queue="routing")

    logger.info("SupplySense disruption reported", extra={"vehicle_id": vehicle_id, "event_type": body.event_type})

    return {
        "disruption_event_id": disruption.event_id,
        "event_type": body.event_type,
        "vehicle_id": vehicle_id,
        "vehicle_code": vehicle.vehicle_code,
        "pending_stops_affected": pending_count,
        "reopt_job_id": reopt_job_id,
        "estimated_completion_sec": 15,
        "poll_url": f"/routes/jobs/{reopt_job_id}",
        "message": "SupplySense re-optimization queued. Driver routes will update automatically when complete.",
    }


@router.post("/vehicles/location")
async def receive_gps_ping(
    body: GPSPingRequest,
    internal_key_valid: bool = Depends(verify_internal_key),
):
    """
    Receive GPS ping from vehicle simulator.
    Auth: X-Internal-Key header (NOT JWT).
    Writes to Redis sorted set (primary). Every 5th ping archives to PostgreSQL.
    Checks proximity to next PENDING stop (500m threshold).
    Publishes to location_updates Redis channel for live map.

    GPS spec: 30-second interval per vehicle. 10 vehicles = 20 pings/min.
    Redis key: supplysense:vehicle:loc:{vehicle_id}
    """
    r = redis.from_url(settings.REDIS_URL, decode_responses=True)
    ts = body.timestamp.timestamp()
    loc_json = json.dumps({"lat": body.lat, "lng": body.lng, "timestamp": body.timestamp.isoformat()})
    redis_key = f"supplysense:vehicle:loc:{body.vehicle_id}"

    # Write to Redis sorted set (score = unix timestamp)
    r.zadd(redis_key, {loc_json: ts})
    r.zremrangebyrank(redis_key, 0, -101)  # keep last 100 pings
    r.expire(redis_key, getattr(settings, "REDIS_LOCATION_TTL_SECONDS", 86400))

    # Every 5th ping: archive to PostgreSQL
    ping_counter_key = f"supplysense:ping:count:{body.vehicle_id}"
    count = r.incr(ping_counter_key)
    
    db_write_n = getattr(settings, "DB_WRITE_EVERY_N_PINGS", 5)
    if int(count) % db_write_n == 0:
        from models.routing import VehicleLocation
        from database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            db.add(VehicleLocation(vehicle_id=body.vehicle_id, timestamp=body.timestamp, lat=body.lat, lng=body.lng))
            await db.commit()

    # Publish to location_updates for live map WebSocket
    location_payload = json.dumps({"vehicle_id": body.vehicle_id, "lat": body.lat, "lng": body.lng, "timestamp": body.timestamp.isoformat()})
    r.publish("location_updates", location_payload)
    r.close()

    # Check proximity to next PENDING stop (500m threshold)
    stop_status_changed = False
    stop_in_progress = None
    from models.routing import Route, RouteStop, DeliveryOrder
    from database import AsyncSessionLocal
    from sqlalchemy import select
    from services.distance_matrix import haversine_minutes

    async with AsyncSessionLocal() as db:
        today = date.today()
        route_result = await db.execute(
            select(Route).where(Route.vehicle_id == body.vehicle_id, Route.delivery_date == today, Route.status == "IN_PROGRESS")
        )
        active_route = route_result.scalar_one_or_none()
        if active_route:
            next_stop_result = await db.execute(
                select(RouteStop).join(DeliveryOrder).where(
                    RouteStop.route_id == active_route.route_id,
                    RouteStop.status == "PENDING",
                ).order_by(RouteStop.sequence).limit(1)
            )
            next_stop = next_stop_result.scalar_one_or_none()
            if next_stop:
                order = await db.get(DeliveryOrder, next_stop.order_id)
                dist_minutes = haversine_minutes(body.lat, body.lng, float(order.lat), float(order.lng))
                speed_fallback = getattr(settings, "SPEED_FALLBACK_KMH", 30)
                arrival_radius = getattr(settings, "ARRIVAL_RADIUS_METRES", 500)
                
                dist_km = dist_minutes * speed_fallback / 60
                if dist_km <= (arrival_radius / 1000):
                    next_stop.status = "IN_PROGRESS"
                    next_stop.arrived_at = body.timestamp
                    await db.commit()
                    stop_status_changed = True
                    # Needs refresh for order relations
                    stop_in_progress = {"stop_id": next_stop.stop_id, "sequence": next_stop.sequence,
                                        "customer_name": order.customer_name, "arrived_at": body.timestamp.isoformat()}
                    await r.publish(f"stop_updates:{body.vehicle_id}", json.dumps(stop_in_progress))

    r.close()

    return {
        "vehicle_id": body.vehicle_id,
        "accepted": True,
        "stop_status_changed": stop_status_changed,
        "stop_in_progress": stop_in_progress,
    }


@router.websocket("/ws/{channel}")
async def websocket_endpoint(
    websocket: WebSocket,
    channel: str,
    token: str = Query(...),
):
    """
    WebSocket for live route and GPS updates.
    Auth: JWT passed as ?token=<JWT> query param.
    WebSocket handshake does NOT support Authorization header.

    Channels:
      route_updates:{depot_id}   — full route solution after optimization
      location_updates           — GPS pings for live map
      stop_updates:{vehicle_id}  — stop status changes for driver view
    """
    from jose import jwt, JWTError
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        user_role = payload.get("role")
        if user_role == "driver":
            allowed_channel = f"stop_updates:{payload.get('vehicle_id')}"
            if channel != allowed_channel:
                await websocket.close(code=4003)
                return
    except JWTError:
        await websocket.close(code=4001)
        return

    await manager.connect(websocket, channel)
    logger.info("SupplySense WebSocket connected", extra={"channel": channel, "user_id": payload.get("user_id")})

    try:
        while True:
            await websocket.receive_text()  # keep connection alive, detect disconnect
    except WebSocketDisconnect:
        manager.disconnect(websocket, channel)
        logger.info("SupplySense WebSocket disconnected", extra={"channel": channel})
