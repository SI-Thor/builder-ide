import torch, time, sys, os
n=int(sys.argv[1]) if len(sys.argv)>1 else 4096
a=torch.randn(n,n,device='cuda',dtype=torch.bfloat16); b=torch.randn(n,n,device='cuda',dtype=torch.bfloat16)
for _ in range(5): a@b
torch.cuda.synchronize(); t=time.time(); it=0
while time.time()-t<float(os.environ.get('SECS','8')):
    for _ in range(10): a@b
    torch.cuda.synchronize(); it+=10
dt=time.time()-t
print(f"{os.environ.get('CUDA_VISIBLE_DEVICES','all')[:22]} sms={torch.cuda.get_device_properties(0).multi_processor_count} {2*n**3*it/dt/1e12:.1f} TFLOPS bf16")
