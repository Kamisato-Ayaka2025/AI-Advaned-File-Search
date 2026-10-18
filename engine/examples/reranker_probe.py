import os
import time

import torch
from sentence_transformers import CrossEncoder

t = time.time()
MODEL = os.environ.get("RERANK_MODEL", r"C:\Users\user\aimem-test\bge-reranker-v2-m3")
m = CrossEncoder(
    MODEL,
    device="cuda",
    trust_remote_code=True,
    model_kwargs={"torch_dtype": torch.float16},
)
print("load", round(time.time() - t, 1))
scores = m.predict(
    [
        ("怎么申请延迟交货的赔偿", "逾期交货应按合同总金额每日 0.5% 支付违约金"),
        ("怎么申请延迟交货的赔偿", "服务器采购报价对比表"),
        ("游戏卡顿掉帧", "显卡温度过高会触发降频，导致游戏掉帧"),
    ],
    batch_size=3,
    show_progress_bar=False,
)
print([round(float(x), 4) for x in scores])
