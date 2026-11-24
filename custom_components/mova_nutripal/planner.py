"""Pure, read-only hybrid decision logic. No network or actuator."""
from datetime import datetime, time
from math import floor, isfinite


def valid_number(value):
    return type(value) in (int, float) and isfinite(value) and value >= 0


def plan(data, options, now):
    result = {"remaining_portions": None, "estimated_distributed": None,
              "forecast": None, "budget": None, "suggested_portions": 0,
              "decision": "unavailable"}
    count = data.get("portions_today")
    weight = options["portion_weight"]
    target = options["target"]
    if type(count) is not int or count < 0 or not valid_number(weight) or weight <= 0 or not valid_number(target):
        return result
    result["estimated_distributed"] = round(count * weight, 2)
    schedule = data.get("schedule")
    if not isinstance(schedule, list):
        return result
    remaining = 0
    completed = 0
    uncertain = False
    upcoming = False
    for meal in schedule:
        if not isinstance(meal, dict) or type(meal.get("status")) is not bool:
            return result
        if not meal["status"]:
            continue
        if (meal.get("repeatType") != 1 or type(meal.get("expireStatus")) is not bool
                or type(meal.get("planFinishStatus")) is not bool
                or type(meal.get("portions")) is not int or meal["portions"] < 1
                or meal.get("supperFlag") != 0):
            return result
        if meal["expireStatus"]:
            uncertain = True
            continue
        try:
            meal_time = time.fromisoformat(meal["feedingTime"])
            due = datetime.combine(now.date(), meal_time, tzinfo=now.tzinfo)
        except (ValueError, TypeError, KeyError):
            return result
        seconds = (due - now).total_seconds()
        if meal["planFinishStatus"]:
            # A future meal reported complete may mean stale/inconsistent data.
            if seconds > 0:
                uncertain = True
            completed += meal["portions"]
            continue
        remaining += meal["portions"]
        if seconds <= 0:
            uncertain = True
        elif seconds <= 30 * 60:
            upcoming = True
    result["remaining_portions"] = remaining
    result["forecast"] = round((count + remaining) * weight, 2)
    result["budget"] = round(max(0, target - result["forecast"]), 2)
    if uncertain or completed > count:
        result["decision"] = "schedule_uncertain"
    elif data.get("online") is not True or data.get("device_status") != 1 or data.get("warning_mask") != 0 or data.get("fault_mask") != 0:
        result["decision"] = "device_not_ready"
    elif not valid_number(data.get("bowl_weight")):
        result["decision"] = "unavailable"
    elif result["budget"] < weight:
        result["decision"] = "budget_reached"
    elif upcoming:
        result["decision"] = "meal_soon"
    elif data["bowl_weight"] > options["threshold"]:
        result["decision"] = "bowl_not_empty"
    else:
        result["suggested_portions"] = min(floor(result["budget"] / weight), options["max_complement"])
        result["decision"] = "would_feed"
    return result
