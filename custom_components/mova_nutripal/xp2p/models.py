"""Video-only model extracted from upstream MIT sources."""
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any
from .video_provisioning_status import classify_xp2p_provisioning_issue

@dataclass(slots=True, frozen=True)
class DreameLawnMowerCameraStreamRuntimeInputs:
    """Runtime inputs needed by a native XP2P video runner."""

    source: str
    did: str
    channel_id: str | None = None
    product_id: str | None = None
    device_name: str | None = None
    p2p_info: str | None = None
    secret_id: str | None = None
    secret_key: str | None = None
    app_id: str | None = None
    app_secret: str | None = None
    lan_client_token: str | None = field(default=None, repr=False)
    stream_channel: str | int = 0
    live_command: str = "action=live"
    flv_path_template: str = (
        "ipc.flv?action=live&channel={channel}&quality=high&_crypto=on"
    )
    diagnostics: Mapping[str, Any] = field(default_factory=dict, repr=False)
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def xp2p_id(self) -> str | None:
        """Return the SDK id shape used by Tencent XP2P examples."""
        if not self.product_id or not self.device_name:
            return None
        return f"{self.product_id}/{self.device_name}"

    @property
    def missing_required(self) -> tuple[str, ...]:
        """Return runtime fields still missing before XP2P can be started."""
        missing: list[str] = []
        for name in ("product_id", "device_name", "p2p_info"):
            if not getattr(self, name):
                missing.append(name)
        return tuple(missing)

    @property
    def ready(self) -> bool:
        """Return whether the minimum XP2P runtime input set is present."""
        return not self.missing_required

    @property
    def provisioning_issue(self) -> str | None:
        """Return a stable issue classified from privacy-safe cloud telemetry."""
        return classify_xp2p_provisioning_issue(
            self.diagnostics,
            missing_required=self.missing_required,
        )

    @property
    def missing_lan_required(self) -> tuple[str, ...]:
        """Return identity fields missing from direct same-LAN startup."""
        return tuple(
            name for name in ("product_id", "device_name") if not getattr(self, name)
        )

    @property
    def lan_identity_ready(self) -> bool:
        """Return whether LAN discovery has enough identity to be attempted."""
        return not self.missing_lan_required

    @property
    def qcloud_credential_state(self) -> str:
        """Return whether Tencent QCloud credentials are complete."""
        return _credential_pair_state(self.secret_id, self.secret_key)

    @property
    def missing_qcloud_credentials(self) -> tuple[str, ...]:
        """Return QCloud credential fields that were not returned by Dreame."""
        return _missing_credential_pair(
            ("secret_id", self.secret_id),
            ("secret_key", self.secret_key),
        )

    @property
    def app_credential_state(self) -> str:
        """Return whether app-level video credentials are complete."""
        return _credential_pair_state(self.app_id, self.app_secret)

    @property
    def missing_app_credentials(self) -> tuple[str, ...]:
        """Return app credential fields that were not returned by Dreame."""
        return _missing_credential_pair(
            ("app_id", self.app_id),
            ("app_secret", self.app_secret),
        )

    def as_dict(self, *, redact: bool = False) -> dict[str, Any]:
        """Return a JSON-safe runtime payload."""
        payload = asdict(self)
        payload["xp2p_id"] = self.xp2p_id
        payload["ready"] = self.ready
        payload["missing_required"] = self.missing_required
        payload["provisioning_issue"] = self.provisioning_issue
        payload["lan_identity_ready"] = self.lan_identity_ready
        payload["missing_lan_required"] = self.missing_lan_required
        payload["qcloud_credential_state"] = self.qcloud_credential_state
        payload["missing_qcloud_credentials"] = self.missing_qcloud_credentials
        payload["app_credential_state"] = self.app_credential_state
        payload["missing_app_credentials"] = self.missing_app_credentials
        if redact:
            for key in (
                "p2p_info",
                "secret_id",
                "secret_key",
                "app_id",
                "app_secret",
                "lan_client_token",
            ):
                payload[f"{key}_present"] = bool(payload.get(key))
                payload.pop(key, None)
            payload.pop("raw", None)
        return payload


def _credential_pair_state(left: str | None, right: str | None) -> str:
    present = (bool(left), bool(right))
    if all(present):
        return "complete"
    if any(present):
        return "partial"
    return "absent"


def _missing_credential_pair(
    left: tuple[str, str | None],
    right: tuple[str, str | None],
) -> tuple[str, ...]:
    return tuple(name for name, value in (left, right) if not value)

