"""Rolling quota for finalized PSIM recordings; active and recent segments survive."""
from .data_store import read_json


def enforce_recording_quota(directory, max_storage_mb):
    directory = directory.resolve()
    active = read_json(directory / 'stare_psim.json').get('segment_id')
    recordings = []
    for meta_path in directory.glob('psim_*_part*_meta.json'):
        if meta_path.is_symlink():
            continue
        meta = read_json(meta_path)
        if meta.get('schema') != 'industrial-drive.sesiune.v2':
            continue
        name = meta_path.name[:-10]
        paths = [directory / (name + suffix) for suffix in ('_samples.csv', '_events.csv', '_meta.json')]
        if any(path.is_symlink() or path.resolve().parent != directory for path in paths):
            continue
        try:
            size = sum(path.stat().st_size for path in paths if path.exists())
            recordings.append((meta_path.stat().st_mtime, name, meta, paths, size))
        except OSError:
            continue
    recordings.sort(reverse=True)
    protected = {item[1] for item in recordings[:2]} | {active}
    total = sum(item[4] for item in recordings)
    for _, name, meta, paths, size in reversed(recordings):
        if total <= max_storage_mb * 1024 * 1024:
            break
        if name in protected or meta.get('achizitie') not in ('OPRIT', 'INREGISTRARE'):
            continue
        try:
            for path in paths:
                path.unlink(missing_ok=True)
            total -= size
        except OSError:
            continue
    return total
