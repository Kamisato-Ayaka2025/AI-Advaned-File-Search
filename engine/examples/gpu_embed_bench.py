import sys
import time

from sentence_transformers import SentenceTransformer

model_name = sys.argv[1] if len(sys.argv) > 1 else "BAAI/bge-small-zh-v1.5"
device = sys.argv[2] if len(sys.argv) > 2 else "cuda"
n = int(sys.argv[3]) if len(sys.argv) > 3 else 2000

m = SentenceTransformer(model_name, device=device)
texts = [f"设备采购方案 第 {i} 版 供应商报价对比表 服务器 网络设备" for i in range(n)]
m.encode(texts[: min(64, n)], batch_size=64, normalize_embeddings=True)  # warmup
t = time.time()
m.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
dt = time.time() - t
print(f"{model_name} on {device}: {n} docs in {dt:.2f}s = {n / dt:.0f} docs/s")
