"""Read-only audit of installed map files against retained release ZIP CRCs."""
import argparse
import json
from pathlib import Path, PurePosixPath
import zipfile
import zlib


def audit(archive, installation, map_name):
    root = Path(installation).resolve()
    checked, missing, mismatched = 0, [], []
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            name = entry.filename.replace("\\", "/")
            path = PurePosixPath(name)
            if entry.is_dir() or not (f"/Maps/{map_name}/" in name or
                                       f"/Maps/OpenDrive/{map_name}." in name):
                continue
            if ".." in path.parts or path.is_absolute():
                raise ValueError("Unsafe archive entry")
            target = root.joinpath(*path.parts).resolve()
            if not target.is_relative_to(root):
                raise ValueError("Installed path escapes installation")
            checked += 1
            if not target.is_file():
                missing.append(name)
                continue
            checksum = 0
            with target.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    checksum = zlib.crc32(chunk, checksum)
            if target.stat().st_size != entry.file_size or checksum != entry.CRC:
                mismatched.append(name)
    return {"archive": str(archive), "map": map_name, "checked": checked,
            "missing": missing, "mismatched": mismatched}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive")
    parser.add_argument("installation")
    parser.add_argument("--map", default="Town13")
    args = parser.parse_args()
    result = audit(args.archive, args.installation, args.map)
    print(json.dumps(result, indent=2))
    raise SystemExit(bool(result["missing"] or result["mismatched"]))
