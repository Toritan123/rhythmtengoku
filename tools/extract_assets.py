#!/usr/bin/env python3
# Extracts graphics, audio and binary assets from baserom.gba using the
# offsets listed in tools/asset_offsets.json.
import sys, os, json, struct, hashlib

ROM_BASE = 0x08000000


class Rom:
    def __init__(self, path):
        with open(path, "rb") as f:
            self.data = f.read()

    def bytes(self, addr, size):
        start = addr - ROM_BASE
        return self.data[start:start + size]

    def u16(self, addr):
        return struct.unpack_from("<H", self.data, addr - ROM_BASE)[0]

    def u32(self, addr):
        return struct.unpack_from("<I", self.data, addr - ROM_BASE)[0]

    def hwords(self, addr, count):
        return list(struct.unpack_from("<%dH" % count, self.data, addr - ROM_BASE))


# Inverse of CompressedData in compression.py
def decompress_nibbles(rom, header):
    data = rom.u32(header)
    size = rom.u16(header + 4)
    segment_count = rom.u16(header + 6)
    window1 = rom.u32(header + 8)
    window2 = rom.u32(header + 12)

    def window_bit(window, index):
        return (rom.u32(window + (index >> 5) * 4) >> (index & 31)) & 1

    def mode_1_decode(nibbles, byte):
        result = 0
        for i in range(4):
            result |= nibbles[(byte >> (i * 2)) & 3] << (i * 4)
        return result

    out = []
    pos = data
    window2_index = 0
    for segment in range(segment_count):
        if not window_bit(window1, segment):
            # Copy mode
            out.append(rom.u16(pos))
            pos += 2
            continue

        mode_1 = window_bit(window2, window2_index)
        window2_index += 1
        if not mode_1:
            # 1:4 ratio
            hword = rom.u16(pos)
            pos += 2
            count = (hword >> 8) + 1
            nibbles = (hword & 0xF, (hword >> 4) & 0xF)
            for encoded in rom.hwords(pos, count):
                for i in range(4):
                    result = 0
                    for j in range(4):
                        result |= nibbles[(encoded >> (i * 4 + j)) & 1] << (j * 4)
                    out.append(result)
            pos += count * 2
        else:
            # 1:2 ratio
            hword = rom.u16(pos)
            nibbles = [(hword >> (i * 4)) & 0xF for i in range(4)]
            hword = rom.u16(pos + 2)
            pos += 4
            count = (hword & 0xFF) + 1
            out.append(mode_1_decode(nibbles, hword >> 8))
            for encoded in rom.hwords(pos, count):
                out.append(mode_1_decode(nibbles, encoded & 0xFF))
                out.append(mode_1_decode(nibbles, encoded >> 8))
            pos += count * 2

    return out[:size]


# Inverse of RleCompressedData in compression.py
def decompress_rle(rom, header):
    data = rom.u32(header)
    segments = rom.u32(header + 4)
    segment_count = rom.u16(header + 8)
    size = rom.u16(header + 10)
    double = rom.u32(header + 12)

    if double:
        values = decompress_nibbles(rom, data)
    else:
        values = None

    def read_count():
        nonlocal segments
        count = 0
        while rom.bytes(segments, 1)[0] == 0:
            count += 255
            segments += 1
        count += rom.bytes(segments, 1)[0]
        segments += 1
        return count

    out = []
    literal = 0
    for segment in range(segment_count):
        count = read_count()
        if segment & 1:
            out.extend([out[-1]] * count)
        else:
            if values is None:
                out.extend(rom.hwords(data + literal * 2, count))
            else:
                out.extend(values[literal:literal + count])
            literal += count

    return struct.pack("<%dH" % size, *out[:size])


def make_wav(rom, header):
    length = rom.u32(header) + 1
    rate = rom.u32(header + 4)
    pcm = rom.u32(header + 20)
    # ROM stores signed 8-bit PCM, WAV uses unsigned
    data = bytes(b ^ 0x80 for b in rom.bytes(pcm, length))
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate, 1, 8)
    info = b"INFO" + b"ISFT" + struct.pack("<I", 14) + b"Lavf57.83.100\x00"
    chunks = (b"fmt " + struct.pack("<I", len(fmt)) + fmt +
              b"LIST" + struct.pack("<I", len(info)) + info +
              b"data" + struct.pack("<I", len(data)) + data)
    if len(data) & 1:
        chunks += b"\x00"
    return b"RIFF" + struct.pack("<I", len(chunks) + 4) + b"WAVE" + chunks


def extract(rom, kind, args):
    if kind == "raw":
        return rom.bytes(int(args[0], 16), args[1])
    if kind == "rle":
        return decompress_rle(rom, int(args[0], 16))
    if kind == "wav":
        return make_wav(rom, int(args[0], 16))
    raise ValueError("Unknown asset type: %s" % kind)


def main():
    manifest_path = os.path.join(os.path.dirname(__file__), "asset_offsets.json")
    with open(manifest_path, "r") as f:
        manifest = json.load(f)

    for rom_path, assets in manifest.items():
        missing = [path for path in assets if not os.path.exists(path)]
        if not missing:
            continue
        if not os.path.exists(rom_path):
            # Only baserom.gba is required, other revisions are optional
            if rom_path == "baserom.gba":
                sys.exit("No ROM provided. Please place an unmodified ROM named \"baserom.gba\" in the root folder")
            print("%s not found, skipping %d assets" % (rom_path, len(missing)))
            continue

        rom = Rom(rom_path)
        for path in missing:
            kind, sha1, *args = assets[path]
            data = extract(rom, kind, args)
            if hashlib.sha1(data).hexdigest() != sha1:
                sys.exit("Extracted %s does not match the expected checksum" % path)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        print("Extracted %d assets from %s" % (len(missing), rom_path))


if __name__ == "__main__":
    main()
