from __future__ import annotations

import json
from pathlib import Path

import numpy as np


class VectorStore:
    """Brute-force float32 cosine store backed by a memmapped .npy file.

    Good to ~1M x 512 on a laptop (2 GB). Swap for sqlite-vec / hnswlib later;
    callers only use add/save/load/search.
    """

    def __init__(self, directory: str | Path) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.mat_path = self.dir / "vectors.npy"
        self.ids_path = self.dir / "vector_ids.json"
        self.ids: list[str] = []
        self.id_to_row: dict[str, int] = {}
        self.mat: np.ndarray | None = None

    # -- persistence --------------------------------------------------------
    def load(self) -> "VectorStore":
        if self.mat_path.exists() and self.ids_path.exists():
            self.mat = np.load(self.mat_path, mmap_mode="r")
            self.ids = json.loads(self.ids_path.read_text("utf-8"))
            self.id_to_row = {uid: i for i, uid in enumerate(self.ids)}
        return self

    def save(self) -> None:
        if self.mat is None:
            np.save(self.mat_path, np.zeros((0, 0), dtype=np.float32))
        else:
            np.save(self.mat_path, np.ascontiguousarray(self.mat))
        self.ids_path.write_text(json.dumps(self.ids), "utf-8")

    # -- mutation -----------------------------------------------------------
    def add(self, ids: list[str], vecs: np.ndarray) -> None:
        vecs = np.asarray(vecs, dtype=np.float32)
        if vecs.size == 0:
            return
        if vecs.ndim == 1:
            vecs = vecs.reshape(1, -1)
        if self.mat is None:
            self.mat = np.zeros((0, vecs.shape[1]), dtype=np.float32)
        elif isinstance(self.mat, np.memmap) or not self.mat.flags.writeable:
            self.mat = np.array(self.mat, dtype=np.float32)

        new_ids: list[str] = []
        new_vecs: list[np.ndarray] = []
        for uid, v in zip(ids, vecs):
            row = self.id_to_row.get(uid)
            if row is None:
                new_ids.append(uid)
                new_vecs.append(v)
            else:
                self.mat[row] = v
        if new_ids:
            block = np.stack(new_vecs)
            start = self.mat.shape[0]
            self.mat = np.vstack([self.mat, block]) if start else block
            for i, uid in enumerate(new_ids):
                self.id_to_row[uid] = start + i
            self.ids.extend(new_ids)

    # -- query --------------------------------------------------------------
    def __len__(self) -> int:
        return len(self.ids)

    def search(self, qvec: np.ndarray, k: int = 200) -> list[tuple[str, float]]:
        if self.mat is None or len(self.ids) == 0:
            return []
        q = np.asarray(qvec, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(q))
        if norm == 0:
            return []
        q = q / norm
        sims = np.asarray(self.mat @ q, dtype=np.float32)
        k = min(k, len(sims))
        if k <= 0:
            return []
        idx = np.argpartition(-sims, k - 1)[:k]
        idx = idx[np.argsort(-sims[idx])]
        return [(self.ids[int(i)], float(sims[int(i)])) for i in idx]
