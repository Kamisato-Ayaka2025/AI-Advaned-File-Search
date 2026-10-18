"""Re-embed an existing index with a different model (no re-extraction).

Environment:
  AIMEM_DB     default C:/Users/user/aimem-test/cdisk.db
  AIMEM_STORE  default C:/Users/user/aimem-test/cdisk_qwen.vectors
  AIMEM_EMBED  default st:Qwen/Qwen3-Embedding-0.6B
  AIMEM_DTYPE  float16 / bfloat16 / float32
  AIMEM_CHARS  truncate embed_text to N chars (default 256)
"""

import os
import time


from aimem import db  # noqa: E402
from aimem.embedders import make_embedder  # noqa: E402
from aimem.vectors import VectorStore  # noqa: E402

DB = os.environ.get("AIMEM_DB", r"C:\Users\user\aimem-test\cdisk.db")
STORE = os.environ.get("AIMEM_STORE", r"C:\Users\user\aimem-test\cdisk_qwen.vectors")
EMBED = os.environ.get("AIMEM_EMBED", "st:Qwen/Qwen3-Embedding-0.6B")
DTYPE = os.environ.get("AIMEM_DTYPE") or None
CHARS = int(os.environ.get("AIMEM_CHARS", "256"))

conn = db.connect(DB)
emb = make_embedder(EMBED, "cuda", dtype=DTYPE)
store = VectorStore(STORE).load()
done = set(store.id_to_row)
print(
    f"embedder={emb.name} dim={emb.dim} dtype={DTYPE} chars={CHARS} resume={len(done)}",
    flush=True,
)

t = time.time()
n = 0
cur = conn.execute("select id, embed_text from units")
while True:
    rows = cur.fetchmany(2048)
    if not rows:
        break
    rows = [r for r in rows if r["id"] not in done]
    if not rows:
        continue
    ids = [r["id"] for r in rows]
    texts = [(r["embed_text"] or "")[:CHARS] for r in rows]
    vecs = emb.encode_documents(texts, batch_size=32)
    store.add(ids, vecs)
    done.update(ids)
    n += len(rows)
    if n % 20480 < 2048:
        store.save()
        print(f"{n} docs  {time.time()-t:.0f}s  {n/max(1,time.time()-t):.0f} docs/s", flush=True)

store.save()
print("DONE", n, "vectors", len(store), "elapsed", round(time.time() - t, 1), flush=True)
