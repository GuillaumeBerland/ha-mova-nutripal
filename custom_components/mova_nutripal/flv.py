"""Convert legacy HEVC FLV tags to Enhanced FLV without transcoding."""
MAX_TAG = 8 * 1024 * 1024


def convert_stream(read):
    """Yield complete FLV header/tags; read(n) must return exactly n bytes."""
    def exact(n):
        data = read(n)
        if len(data) != n:
            raise EOFError("Incomplete FLV data")
        return data

    header = exact(9)
    if header[:3] != b"FLV" or header[3] != 1:
        raise ValueError("Invalid FLV header")
    size = int.from_bytes(header[5:9], "big")
    if not 9 <= size <= 4096:
        raise ValueError("Invalid FLV header size")
    yield header + exact(size - 9 + 4)

    while True:
        header = bytearray(exact(11))
        tag_type = header[0] & 0x1F
        size = int.from_bytes(header[1:4], "big")
        if size > MAX_TAG:
            raise ValueError("Oversized FLV tag")
        payload = exact(size)
        if int.from_bytes(exact(4), "big") != 11 + size:
            raise ValueError("Invalid FLV tag size")
        if tag_type == 18:
            continue  # Legacy metadata can advertise codec ID 12.
        if tag_type == 9 and payload and payload[0] & 15 == 12 and not payload[0] & 128:
            if len(payload) < 5:
                raise ValueError("Short legacy HEVC tag")
            frame_type, packet_type = payload[0] >> 4, payload[1]
            if frame_type not in (1, 2, 3, 4, 5) or packet_type not in (0, 1, 2):
                raise ValueError("Unsupported legacy HEVC tag")
            prefix = bytes([128 | (frame_type << 4) | packet_type]) + b"hvc1"
            payload = prefix + (payload[2:] if packet_type == 1 else payload[5:])
        header[1:4] = len(payload).to_bytes(3, "big")
        yield bytes(header) + payload + (11 + len(payload)).to_bytes(4, "big")
