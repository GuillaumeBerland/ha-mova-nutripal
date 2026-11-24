"""Read-only MOVA video provisioning; no device control or pairing."""
from dataclasses import dataclass, field


class VideoError(RuntimeError):
    """Camera error containing only a safe diagnostic stage."""


@dataclass(frozen=True, repr=False)
class VideoIdentity:
    device_id: str
    product_id: str
    device_name: str
    secret_id: str = field(repr=False)
    secret_key: str = field(repr=False)
    p2p_info: str = field(repr=False)


def _read(cloud, endpoint, params):
    try:
        response = cloud._api_call("dreame-third-video/tx/" + endpoint, params, retry_count=0, timeout=15)
    except Exception:
        raise VideoError("video_cloud_request") from None
    if not isinstance(response, dict) or response.get("code") != 0:
        raise VideoError("video_cloud_response")
    result = response.get("data")
    if isinstance(result, dict) and "data" in result:
        result = result["data"]
    if not isinstance(result, dict):
        raise VideoError("video_cloud_payload")
    return result


def _required(data, key):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise VideoError("video_identity_incomplete")
    return value


def provision(cloud, did, model):
    """Fetch only the four endpoints validated on NutriPal q2503."""
    token = _required(_read(cloud, "user/accesstoken", {"os": 1}), "token")
    params = {"did": str(did), "os": 1, "accesstoken": token, "accessToken": token}
    if _read(cloud, "dev/isDevUser", params).get("isDevUser") is not True:
        raise VideoError("video_permission_denied")
    identity_params = {**params, "model": model}
    uid = getattr(cloud, "_uid", None)
    if uid:
        identity_params["uid"] = str(uid)
    identity = _read(cloud, "mgr/dev/getIdentity", identity_params)
    p2p = _read(cloud, "dev/getP2PInfo", params)
    return VideoIdentity(*(_required(identity, key) for key in (
        "deviceId", "productId", "deviceName", "secretId", "secretKey")),
        _required(p2p, "p2pInfo"))
