import os, sys, time, json, torch
role = sys.argv[1]            # live | bg
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 15
dev = torch.device('cuda')
props = torch.cuda.get_device_properties(0)
if role == 'bg':
    # streaming background: 2 GiB working set, elementwise read+write, no gaps
    n = (1 << 30) // 2           # 0.5 G fp16 = 1 GiB per tensor, two tensors = 2 GiB
    a = torch.ones(n, dtype=torch.float16, device=dev); b = torch.empty_like(a)
    torch.cuda.synchronize(); t0 = time.time(); it = 0
    while time.time() - t0 < secs:
        torch.add(a, 1.0, out=b); torch.add(b, -1.0, out=a); it += 1
        if it % 8 == 0: torch.cuda.synchronize()
    torch.cuda.synchronize(); dt = time.time() - t0
    print(json.dumps({"role": "bg", "sms": props.multi_processor_count, "GBps": round(it * 2 * 2 * 2 * n / dt / 1e9, 1)}))
else:
    # live: a d1-sized GEMV, ~64 MB of weights read per launch, every 10 ms
    W = torch.randn(8192, 4096, dtype=torch.float16, device=dev); x = torch.randn(4096, 1, dtype=torch.float16, device=dev)
    for _ in range(20): W @ x
    torch.cuda.synchronize()
    dev_ms, host_ms, on_cadence = [], [], 0
    t_end = time.time() + secs; next_t = time.time()
    while time.time() < t_end:
        while time.time() < next_t: pass
        s, e = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
        h0 = time.perf_counter(); s.record(); y = W @ x; e.record(); e.synchronize(); h1 = time.perf_counter()
        dev_ms.append(s.elapsed_time(e)); host_ms.append((h1 - h0) * 1e3)
        if (h1 - h0) * 1e3 <= 10.0: on_cadence += 1
        next_t += 0.010
    q = lambda v, p: sorted(v)[min(len(v) - 1, int(p * len(v)))]
    print(json.dumps({"role": "live", "sms": props.multi_processor_count, "launches": len(dev_ms), "on_cadence": on_cadence,
                      "dev_p50_ms": round(q(dev_ms, .5), 3), "dev_p99_ms": round(q(dev_ms, .99), 3),
                      "host_p50_ms": round(q(host_ms, .5), 3), "host_p99_ms": round(q(host_ms, .99), 3)}))
