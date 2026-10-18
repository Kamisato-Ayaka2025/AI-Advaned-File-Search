"""Build a real C:/D: index with the Windows GPU environment.

Run with the Windows venv python (see README). Paths are hard-coded here so that
Chinese directory names survive the WSL -> PowerShell hand-off.
"""

import time


from aimem import db  # noqa: E402
from aimem.embedders import make_embedder  # noqa: E402
from aimem.index.indexer import Indexer  # noqa: E402
from aimem.vectors import VectorStore  # noqa: E402

DB = r"C:\Users\user\aimem-test\cdisk.db"
ROOTS = [
    r"C:\Users\user\Desktop",
    r"C:\Users\user\Documents",
    r"C:\Users\user\Downloads",
    r"C:\Users\user\OneDrive",
    r"C:\Users\user\source",
    r"D:\BaiduNetdiskDownload",
    r"D:\电脑管家迁移文件",
    r"D:\Android stdio projects",
    r"D:\迅雷下载",
]

t0 = time.time()
conn = db.connect(DB)
store = VectorStore(r"C:\Users\user\aimem-test\cdisk.vectors").load()
emb = make_embedder("st:BAAI/bge-small-zh-v1.5", "cuda")
indexer = Indexer(conn, store, emb, batch_size=64)
stats = indexer.index_files(
    ROOTS,
    max_files=100_000,
    max_chars=3000,
    max_chunks=6,
)
print("RESULT", stats.summary())
print("ELAPSED", round(time.time() - t0, 1), "s")
print("STATS", db.stats(conn))
