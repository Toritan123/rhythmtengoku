#!/usr/bin/env python3
# Regenerates tools/asset_offsets.json from matching builds of both revisions.
# Usage: gen_asset_offsets.py [rev0.elf] [rev1.elf]
# Since both revisions share the build folder, copy one ELF elsewhere before
# running `make clean` and building the other. Every asset file must be present;
# new assets are picked up automatically as long as they follow the existing
# naming conventions.
import sys, os, re, json, hashlib, subprocess

ROMS = (
    ("baserom.gba", "build/rhythmtengoku.elf"),
    ("baserom_rev1.gba", "build/rhythmtengoku_rev1.elf"),
)
ASSET_DIRS = ("audio/samples", "audio/sequences", "bin", "graphics", "games")
RAW_EXTENSIONS = (".bin", ".mid", ".raw.4bpp")
RLE_EXTENSIONS = (".4bpp", ".tilemap")


def read_symbols(elf):
    output = subprocess.check_output(["arm-none-eabi-nm", elf], text=True)
    symbols = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) == 3:
            symbols[parts[2]] = int(parts[0], 16)
    return symbols


def find_assets():
    assets = []
    for top in ASSET_DIRS:
        for root, dirs, files in os.walk(top):
            for name in files:
                if name.endswith(".wav") or name.endswith(RAW_EXTENSIONS) or name.endswith(RLE_EXTENSIONS):
                    assets.append(os.path.join(root, name))
    return sorted(assets)


def main():
    symbol_tables = []
    for i, (rom, elf) in enumerate(ROMS):
        if len(sys.argv) > i + 1:
            elf = sys.argv[i + 1]
        if os.path.exists(elf):
            symbol_tables.append((rom, read_symbols(elf)))
    manifest = {rom: {} for rom, elf in symbol_tables}
    missing = []

    for path in find_assets():
        name = os.path.basename(path)
        with open(path, "rb") as f:
            data = f.read()
        sha1 = hashlib.sha1(data).hexdigest()

        if name.endswith(".wav"):
            symbol = name.split(".")[0] + "_data"
            entry = ["wav", sha1, symbol]
        elif name.endswith(RAW_EXTENSIONS):
            # Symbol naming used by bin2s
            symbol = re.sub(r"[^A-Za-z0-9_]", "_", name)
            entry = ["raw", sha1, symbol, len(data)]
        else:
            symbol = name.split(".")[0]
            entry = ["rle", sha1, symbol]

        # Use the first ROM that contains the asset
        for rom, symbols in symbol_tables:
            if symbol in symbols:
                if entry[0] == "raw" and symbols.get(symbol + "_end", 0) - symbols[symbol] != len(data):
                    sys.exit("Size mismatch for %s" % path)
                entry[2] = "0x%08x" % symbols[symbol]
                manifest[rom][path] = entry
                break
        else:
            missing.append(path)

    for path in missing:
        print("Not found in any ROM, keeping in the repository: %s" % path)

    with open(os.path.join(os.path.dirname(__file__), "asset_offsets.json"), "w") as f:
        f.write("{\n")
        f.write(",\n".join(
            "    %s: {\n%s\n    }" % (json.dumps(rom), ",\n".join(
                "        %s: %s" % (json.dumps(path), json.dumps(entry)) for path, entry in assets.items()))
            for rom, assets in manifest.items()))
        f.write("\n}\n")
    for rom, assets in manifest.items():
        print("Wrote %d asset offsets for %s" % (len(assets), rom))


if __name__ == "__main__":
    main()
