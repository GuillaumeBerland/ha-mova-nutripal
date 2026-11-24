"""Cloud adapter; explicit manual action only."""
from threading import RLock
from .control import send_one
from .const import MODEL
from .dreame_cloud.protocol import DreameVacuumDreameHomeCloudProtocol

PREFIX = "mova/mova-pet/mova-pet-feeder"
PROPERTIES = {(2, 1): "device_status", (2, 2): "warning_mask", (2, 3): "fault_mask", (2, 4): "bowl_weight", (2, 5): "supplement_remaining", (3, 1): "battery", (3, 2): "feeding_mode", (3, 5): "configured_weight", (3, 9): "child_lock", (1000, 1): "camera_enabled", (1000, 2): "sd_card_status"}


class CloudError(Exception):
    pass


class NutriPalAPI:
    def __init__(self, username, password):
        self.cloud = DreameVacuumDreameHomeCloudProtocol(username=username, password=password, account_type="mova", country="eu")
        self.device = None
        self.lock = RLock()

    def close(self):
        with self.lock:
            for key in list(self.cloud._conns):
                self.cloud._close_conn(key)

    def discover(self, did=None):
        if not self.cloud.login():
            raise CloudError("Login failed")
        response = self.cloud.get_devices()
        if not isinstance(response, dict):
            raise CloudError("Device list unavailable")
        devices = [d for d in response.get("page", {}).get("records", []) if d.get("model") == MODEL]
        if did is not None:
            devices = [d for d in devices if str(d.get("did")) == str(did)]
        if len(devices) != 1:
            raise CloudError("Expected exactly one matching feeder")
        self.device = devices[0]
        self.cloud._did = str(self.device["did"])
        self.cloud._host = self.device["bindDomain"]
        self.cloud._model = MODEL
        return self.device

    def call(self, endpoint, params):
        response = self.cloud._api_call(f"{PREFIX}/{endpoint}", {"did": int(self.device["did"]), "model": MODEL, **params}, retry_count=0, timeout=15)
        if not isinstance(response, dict) or response.get("code") != 200:
            return None
        return response.get("data")

    def feed_one(self):
        with self.lock:
            return send_one(self.cloud, self.device["did"])

    def snapshot(self, now):
        with self.lock:
            return self._snapshot(now)

    def _snapshot(self, now):
        if self.device is None:
            raise CloudError("Device not initialized")
        data = {}
        response = self.cloud.get_devices()
        if isinstance(response, dict):
            device = next((d for d in response.get("page", {}).get("records", []) if str(d.get("did")) == str(self.device["did"])), None)
            if device:
                self.device = device
                self.cloud._host = device["bindDomain"]
                data["online"] = device.get("online")
        for group in ([k for k in PROPERTIES if k[0] != 1000], [k for k in PROPERTIES if k[0] == 1000]):
            result = self.cloud.send("get_properties", [{"did": str(self.device["did"]), "siid": s, "piid": p} for s, p in group], retry_count=0, timeout=15)
            if isinstance(result, list):
                for item in result:
                    key = PROPERTIES.get((item.get("siid"), item.get("piid")))
                    if key and item.get("code") == 0:
                        data[key] = item.get("value")
        from datetime import timedelta
        def date_params(date):
            return {"startLocalDateTime": date.strftime("%Y-%m-%d 00:00:00"), "zone": "Europe/Paris"}
        for suffix, date in (("today", now), ("yesterday", now - timedelta(days=1))):
            params = date_params(date)
            intake = self.call("video/record/queryDailyIntakeGrams", params)
            if isinstance(intake, dict):
                data[f"intake_{suffix}"] = intake.get("totalInTakeGrams")
                data[f"meals_{suffix}"] = intake.get("totalInTakeTimes")
            portions = self.call("work/record/queryDailyGrain", {**params, "dateRange": 1})
            if type(portions) is int and portions >= 0:
                data[f"portions_{suffix}"] = portions
        material = self.call("consume/material/query", {"materialType": 1})
        if isinstance(material, dict):
            data["desiccant_days"] = material.get("materialRemainDays")
        if data.get("feeding_mode") is not None:
            schedule = self.call("feeding/plan/queryPlanFinished", {**date_params(now), "planType": data["feeding_mode"]})
            if isinstance(schedule, dict) and isinstance(schedule.get("feedingPlanRespList"), list):
                data["schedule_date"] = now.date().isoformat()
                fields = ("feedingTime", "portions", "repeatType", "status", "supperFlag", "expireStatus", "planFinishStatus")
                data["schedule"] = [{key: row.get(key) for key in fields} for row in schedule["feedingPlanRespList"] if isinstance(row, dict)] if all(isinstance(row, dict) for row in schedule["feedingPlanRespList"]) else None
        if not any(k in data for k in ("intake_today", "device_status", "portions_today")):
            raise CloudError("No fresh data")
        if data.get("battery") == -1:
            data["battery_present"] = False
            data["battery"] = None
        elif type(data.get("battery")) is int and 0 <= data["battery"] <= 100:
            data["battery_present"] = True
        else:
            data["battery"] = None
        return data
