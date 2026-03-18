# SupplySense AI Module - services/solver.py

import time
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
from config import logger, ORTOOLS_CONFIG

def solve(
    distance_matrix: list[list[int]],
    vehicles: list[dict],
    orders: list[dict],
    time_limit_sec: int,
    depot_open_minutes: int = 480,
) -> dict:
    """
    Solve the vehicle routing problem and return optimal stop assignments.

    Args:
        distance_matrix: 2D list of ints (travel time in minutes).
                         Index 0 = depot. Index 1..N = delivery stops.
        vehicles: list of dicts, each has:
                  vehicle_id (int), capacity_kg (float), capacity_m3 (float)
        orders: list of dicts, each has:
                order_id (int), weight_kg (float), volume_m3 (float),
                time_window_open_min (int),   # minutes from midnight e.g. 09:00 = 540
                time_window_close_min (int)   # minutes from midnight e.g. 13:00 = 780
        time_limit_sec: int — hard solver time limit. Returns best found so far at limit.
                        Never raises TimeoutError — always returns a result.
        depot_open_minutes: int — when vehicles can depart depot (default 8:00 AM = 480)

    Returns dict:
    {
      "status": "OPTIMAL" | "FEASIBLE" | "INFEASIBLE",
      "routes": [
        {
          "vehicle_id": int,
          "vehicle_index": int,
          "stop_sequence": [int, ...],   # order indices into distance_matrix (1-based)
          "order_ids": [int, ...],       # order_id for each stop in visit order
          "total_travel_min": int,
          "total_time_min": int,         # travel + service time
        }
      ],
      "unassigned_order_ids": [int, ...],
      "total_travel_min": int,
      "optimization_runtime_ms": int,
    }
    """
    # STEP 1 — Record start time for runtime measurement
    start_ms = int(time.time() * 1000)

    # STEP 2 — Create OR-Tools manager and routing model
    num_locations = 1 + len(orders)   # depot (index 0) + all stops
    num_vehicles = len(vehicles)
    depot_index = 0
    manager = pywrapcp.RoutingIndexManager(num_locations, num_vehicles, depot_index)
    routing = pywrapcp.RoutingModel(manager)

    # STEP 3 — Register distance callback (used for arc costs)
    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return distance_matrix[from_node][to_node]
        
    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # STEP 4 — Register time callback (travel + service time per stop)
    if isinstance(ORTOOLS_CONFIG, dict):
        SERVICE_TIME = ORTOOLS_CONFIG.get("SERVICE_TIME_PER_STOP_MIN", 10)
    else:
        SERVICE_TIME = getattr(ORTOOLS_CONFIG, "SERVICE_TIME_PER_STOP_MIN", 10)
        
    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        travel = distance_matrix[from_node][to_node]
        # Add service time at origin node (not at depot)
        service = SERVICE_TIME if from_node != depot_index else 0
        return travel + service
        
    time_callback_index = routing.RegisterTransitCallback(time_callback)

    # STEP 5 — Add Time dimension with time windows
    if isinstance(ORTOOLS_CONFIG, dict):
        MAX_ROUTE_DURATION = ORTOOLS_CONFIG.get("MAX_ROUTE_DURATION_MIN", 480)
    else:
        MAX_ROUTE_DURATION = getattr(ORTOOLS_CONFIG, "MAX_ROUTE_DURATION_MIN", 480)

    routing.AddDimension(
        time_callback_index,
        slack_max=60,           # allow up to 60 min early arrival waiting
        capacity=MAX_ROUTE_DURATION,           # MAX_ROUTE_DURATION_MIN from ORTOOLS_CONFIG
        fix_start_cumul_to_zero=False,
        name="Time"
    )
    time_dimension = routing.GetDimensionOrDie("Time")
    
    # Set depot start time constraint
    for vehicle_idx in range(num_vehicles):
        start_index = routing.Start(vehicle_idx)
        time_dimension.CumulVar(start_index).SetMin(depot_open_minutes)
        
    # Set time window constraints for each stop
    for stop_idx, order in enumerate(orders):
        node_index = stop_idx + 1  # stops start at index 1 (depot is 0)
        index = manager.NodeToIndex(node_index)
        time_dimension.CumulVar(index).SetRange(
            order["time_window_open_min"],
            order["time_window_close_min"],
        )

    # STEP 6 — Add Weight capacity dimension
    def weight_demand_callback(from_index):
        from_node = manager.IndexToNode(from_index)
        if from_node == depot_index:
            return 0
        return int(orders[from_node - 1]["weight_kg"] * 100)
        
    weight_callback_index = routing.RegisterUnaryTransitCallback(weight_demand_callback)
    vehicle_weight_capacities = [int(v["capacity_kg"] * 100) for v in vehicles]
    
    routing.AddDimensionWithVehicleCapacity(
        weight_callback_index,
        slack_max=0,
        vehicle_capacities=vehicle_weight_capacities,
        fix_start_cumul_to_zero=True,
        name="Weight",
    )

    # STEP 7 — Add Volume capacity dimension
    def volume_demand_callback(from_index):
        from_node = manager.IndexToNode(from_index)
        if from_node == depot_index:
            return 0
        return int(orders[from_node - 1]["volume_m3"] * 1000)
        
    volume_callback_index = routing.RegisterUnaryTransitCallback(volume_demand_callback)
    vehicle_volume_capacities = [int(v["capacity_m3"] * 1000) for v in vehicles]
    
    routing.AddDimensionWithVehicleCapacity(
        volume_callback_index,
        slack_max=0,
        vehicle_capacities=vehicle_volume_capacities,
        fix_start_cumul_to_zero=True,
        name="Volume",
    )

    # STEP 8 — Set search parameters
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_parameters.time_limit.seconds = time_limit_sec

    # STEP 9 — Solve and parse solution
    solution = routing.SolveWithParameters(search_parameters)
    runtime_ms = int(time.time() * 1000) - start_ms

    all_order_ids = [order["order_id"] for order in orders]

    if not solution:
        logger.info(f"SupplySense solver: status=INFEASIBLE vehicles=0 stops=0 time={runtime_ms}ms")
        return {
            "status": "INFEASIBLE", 
            "routes": [], 
            "unassigned_order_ids": all_order_ids,
            "total_travel_min": 0, 
            "optimization_runtime_ms": runtime_ms
        }

    status_code = routing.status()
    if status_code == 1:
        status_str = "OPTIMAL"
    elif status_code == 2:
        status_str = "FEASIBLE"
    else:
        status_str = "INFEASIBLE"

    routes = []
    assigned_order_ids = set()
    total_travel_min = 0

    for vehicle_idx in range(num_vehicles):
        index = routing.Start(vehicle_idx)
        stop_sequence = []
        route_order_ids = []
        route_travel_min = 0
        route_time_min = 0 # Track total time including service time
        
        while not routing.IsEnd(index):
            node_index = manager.IndexToNode(index)
            if node_index != depot_index:
                stop_sequence.append(node_index)
                order_id = orders[node_index - 1]["order_id"]
                route_order_ids.append(order_id)
                assigned_order_ids.add(order_id)
                
            previous_index = index
            index = solution.Value(routing.NextVar(index))
            
            # calculate travel time between previous node and current node
            from_node = manager.IndexToNode(previous_index)
            to_node = manager.IndexToNode(index)
            
            route_travel_min += distance_matrix[from_node][to_node]
            # Service time is only added for stops (not the depot)
            service_time = SERVICE_TIME if from_node != depot_index else 0
            route_time_min += distance_matrix[from_node][to_node] + service_time
            
        if stop_sequence:
            routes.append({
                "vehicle_id": vehicles[vehicle_idx]["vehicle_id"],
                "vehicle_index": vehicle_idx,
                "stop_sequence": stop_sequence,
                "order_ids": route_order_ids,
                "total_travel_min": route_travel_min,
                "total_time_min": route_time_min,
            })
            total_travel_min += route_travel_min

    unassigned_order_ids = [oid for oid in all_order_ids if oid not in assigned_order_ids]

    if not routes and status_str != "INFEASIBLE":
        status_str = "INFEASIBLE"

    logger.info(f"SupplySense solver: status={status_str} vehicles={len(routes)} stops={len(assigned_order_ids)} time={runtime_ms}ms")

    return {
        "status": status_str,
        "routes": routes,
        "unassigned_order_ids": unassigned_order_ids,
        "total_travel_min": total_travel_min,
        "optimization_runtime_ms": runtime_ms,
    }
