import sys
import time

import torch

print("python", sys.version.split()[0])
print("torch", torch.__version__)
print("cuda available", torch.cuda.is_available())
if torch.cuda.is_available():
    print("device", torch.cuda.get_device_name(0))
    print("capability", torch.cuda.get_device_capability(0))
    print("vram GB", round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 1))
    x = torch.randn(4096, 4096, device="cuda")
    t = time.time()
    for _ in range(10):
        x = x @ x
    torch.cuda.synchronize()
    print("matmul 4096^3 x10:", round(time.time() - t, 2), "s")
