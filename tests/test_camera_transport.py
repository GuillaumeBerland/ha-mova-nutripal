"""Offline tests; no Home Assistant, credentials, network or native runtime."""
import importlib
import io
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/mova_nutripal"
PACKAGE = "nutripal_camera_test"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
flv = importlib.import_module(PACKAGE + ".flv")
cloud_video = importlib.import_module(PACKAGE + ".cloud_video")
video = importlib.import_module(PACKAGE + ".video")
HEADER = b"FLV\x01\x05\x00\x00\x00\x09\x00\x00\x00\x00"


def tag(kind, payload):
    return (bytes([kind]) + len(payload).to_bytes(3, "big") + b"\x00\x00\x2a\x00\x00\x00\x00"
            + payload + (11 + len(payload)).to_bytes(4, "big"))


def converted(*tags):
    source = io.BytesIO(HEADER + b"".join(tags))
    stream = flv.convert_stream(source.read)
    result = [next(stream) for _ in range(1 + len(tags))]
    return b"".join(result)


class FlvTests(unittest.TestCase):
    def test_configuration(self):
        self.assertEqual(converted(tag(9, b"\x1c\x00\x00\x00\x00abc")),
                         HEADER + tag(9, b"\x90hvc1abc"))

    def test_video_preserves_composition_and_data(self):
        self.assertEqual(converted(tag(9, b"\x2c\x01\xff\xff\xfeabc")),
                         HEADER + tag(9, b"\xa1hvc1\xff\xff\xfeabc"))

    def test_end(self):
        self.assertEqual(converted(tag(9, b"\x1c\x02\x00\x00\x00")),
                         HEADER + tag(9, b"\x92hvc1"))

    def test_audio_passthrough(self):
        packet = tag(8, b"\xaf\x01abc")
        self.assertEqual(converted(packet), HEADER + packet)

    def test_h264_passthrough(self):
        packet = tag(9, b"\x17\x01\x00\x00\x00abc")
        self.assertEqual(converted(packet), HEADER + packet)

    def test_enhanced_passthrough(self):
        packet = tag(9, b"\x90hvc1abc")
        self.assertEqual(converted(packet), HEADER + packet)

    def test_metadata_dropped(self):
        packet = tag(8, b"audio")
        reader = io.BytesIO(HEADER + tag(18, b"metadata") + packet).read
        stream = flv.convert_stream(reader)
        self.assertEqual(next(stream), HEADER)
        self.assertEqual(next(stream), packet)

    def test_truncated(self):
        with self.assertRaises(EOFError):
            converted(tag(9, b"\x1c\x00\x00\x00\x00abc")[:-2])

    def test_bad_previous_size(self):
        with self.assertRaises(ValueError):
            converted(tag(8, b"abc")[:-4] + b"\x00" * 4)

    def test_invalid_packet_type(self):
        with self.assertRaises(ValueError):
            converted(tag(9, b"\x1c\x03\x00\x00\x00"))

    def test_invalid_header(self):
        with self.assertRaises(ValueError):
            next(flv.convert_stream(io.BytesIO(b"BAD" + HEADER[3:]).read))


class FakeCloud:
    _uid = "uid"

    def __init__(self, allowed=True, complete=True):
        self.calls = []
        self.allowed = allowed
        self.complete = complete

    def _api_call(self, endpoint, params, **kwargs):
        self.calls.append((endpoint, params, kwargs))
        values = {
            "user/accesstoken": {"token": "test-token"},
            "dev/isDevUser": {"isDevUser": self.allowed},
            "mgr/dev/getIdentity": {"deviceId": "dev", "productId": "prod", "deviceName": "name", "secretId": "id", "secretKey": "key" if self.complete else ""},
            "dev/getP2PInfo": {"p2pInfo": "p2p"},
        }
        return {"code": 0, "data": {"requestId": "test", "data": values[endpoint.removeprefix("dreame-third-video/tx/")]}}


class ProvisionTests(unittest.TestCase):
    def test_success(self):
        cloud = FakeCloud()
        identity = cloud_video.provision(cloud, "did", "mova.feeder.q2503")
        self.assertEqual(identity.product_id, "prod")
        self.assertEqual(identity.p2p_info, "p2p")
        self.assertEqual(len(cloud.calls), 4)
        self.assertEqual(cloud.calls[2][1]["uid"], "uid")
        self.assertTrue(all(c[2]["retry_count"] == 0 for c in cloud.calls))
        self.assertNotIn("p2p", repr(identity))
        self.assertNotIn("secret", repr(identity))

    def test_permission_denied_stops(self):
        cloud = FakeCloud(allowed=False)
        with self.assertRaisesRegex(cloud_video.VideoError, "video_permission_denied"):
            cloud_video.provision(cloud, "did", "model")
        self.assertEqual(len(cloud.calls), 2)

    def test_missing_identity(self):
        with self.assertRaisesRegex(cloud_video.VideoError, "video_identity_incomplete"):
            cloud_video.provision(FakeCloud(complete=False), "did", "model")

    def test_reject_remote_url(self):
        for url in ("http://192.168.1.2/", "https://127.0.0.1/", "http://user:pass@localhost/", "http://localhost.example.org/"):
            with self.subTest(url=url), self.assertRaises(cloud_video.VideoError):
                video._local_target(url)

    def test_local_url(self):
        self.assertEqual(video._local_target("http://127.0.0.1:1234/ipc.flv?a=b"), ("127.0.0.1", 1234, "/ipc.flv?a=b"))
