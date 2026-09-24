"""Validate every map member before writing anything outside a dry run."""
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile

def map_members(archive, root):
    root = Path(root).resolve()
    content = (root / 'CarlaUE4' / 'Content').resolve()
    if not content.is_relative_to(root):
        raise ValueError('Map content directory escapes installation')
    selected = []
    seen = set()
    for member in archive.infolist():
        name = member.filename.replace('\\', '/')
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or ':' in name or '\x00' in name:
            raise ValueError(f'Unsafe archive path: {name}')
        if stat.S_ISLNK(member.external_attr >> 16):
            raise ValueError(f'Archive links are forbidden: {name}')
        if path.parts[:2] != ('CarlaUE4', 'Content'):
            continue
        if any(part.rstrip(' .') != part or part.split('.')[0].upper() in
               {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}
               for part in path.parts):
            raise ValueError(f'Unsafe Windows archive path: {name}')
        target = (root / Path(*path.parts)).resolve()
        if not target.is_relative_to(content):
            raise ValueError(f'Archive path escapes content: {name}')
        key = str(target).casefold()
        if key in seen:
            raise ValueError(f'Duplicate archive target: {name}')
        seen.add(key)
        selected.append((member, target))
    if not any(not member.is_dir() for member, _ in selected):
        raise ValueError('Archive contains no CARLA map assets')
    return selected

def install(archive_path, root, extract=False):
    with zipfile.ZipFile(archive_path) as archive:
        members = map_members(archive, root)
        if extract:
            bad = archive.testzip()
            if bad:
                raise ValueError(f'Archive checksum failed: {bad}')
            for member, target in members:
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, target.open('wb') as output:
                        shutil.copyfileobj(source, output)
        return len(members)

if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive');parser.add_argument('root')
    parser.add_argument('--extract',action='store_true')
    args=parser.parse_args()
    print(('Installed' if args.extract else 'Dry run; validated'), install(args.archive,args.root,args.extract), 'map entries')
