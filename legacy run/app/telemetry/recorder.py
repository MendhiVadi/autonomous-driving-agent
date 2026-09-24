"""Replayable JSONL episode logger; no training is performed here."""
import json
import time
from pathlib import Path


class EpisodeRecorder:
    def __init__(self, directory="episodes", episode_name=None, flush_every=20):
        if type(flush_every) is not int or flush_every <= 0:
            raise ValueError("flush_every must be a positive integer")
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = episode_name or time.strftime("episode-%Y%m%d-%H%M%S")
        if not isinstance(stamp, str) or any(c in stamp for c in ("/", "\\", ":")) or stamp in (".", ".."):
            raise ValueError("Episode name must be a filename, not a path")
        suffix = 0
        while True:
            candidate = directory / (f"{stamp}.jsonl" if suffix == 0 else f"{stamp}-{suffix}.jsonl")
            try:
                self.handle = candidate.open("x", encoding="utf-8")
            except FileExistsError:
                suffix += 1
                continue
            self.path = candidate
            break
        self.flush_every = flush_every
        self.pending_records = 0

    def record(self, observation, action, telemetry=None, event=None, metadata=None):
        row = {"timestamp": time.time(), "observation": observation,
               "action": action, "telemetry": telemetry or {}, "event": event}
        if metadata:
            row["metadata"] = metadata
        self.handle.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
        self.pending_records += 1
        if event or self.pending_records >= self.flush_every:
            self.flush()

    def flush(self):
        self.handle.flush()
        self.pending_records = 0

    def close(self):
        if not self.handle.closed:
            try:
                self.flush()
            finally:
                self.handle.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
