# Open 3D generation models for Jetson AGX Thor: licence, feasibility, and spike order

The shortlist resolves to one clear first spike: **TRELLIS.2**, and along one specific path — the native implementation ComfyUI shipped in version 0.34.0 on 2026-08-31, not Microsoft's reference pipeline [10]. The reference pipeline is MIT-licensed and genuinely produces PBR meshes, but its dependency chain (flash-attn, nvdiffrast, nvdiffrec, CuMesh, FlexGEMM, O-Voxel) either has no aarch64 wheels at all or pulls in a renderer licensed for non-commercial use. The ComfyUI port re-implements the same 4B model in plain PyTorch and SciPy, which removes both the build problem and the licence problem in one move [10][11]. Everything else on the list has a defensible reason to be second, later, or skipped.

Two framing corrections matter more than the ranking itself. First, the Thor's 122 GB of unified memory makes every published VRAM requirement a non-issue: TRELLIS.2 asks for at least 24 GB, Hunyuan3D 2.1 for 29 GB, SPAR3D for 10.5 GB [8][20][28]. The models that fail on this box fail on toolchain, not capacity. Second, the speed figures attached to these projects are datacenter numbers with the hardware swapped out. TripoSR's "less than 0.5 seconds" is an NVIDIA A100 measurement [14], and TRELLIS.2's 3 s / 17 s / 60 s ladder is an H100 measurement [8]. No Thor or Jetson benchmark of any model on this list is published, so the scheduler's throughput table has to be filled in by measuring the box, not by copying the model cards.

## 1. Thor constraints: memory, toolchain, and Python version

JetPack 7.2.1 is the platform under test: Jetson Linux 39.2.1, CUDA 13.2.2, TensorRT 10.16.2, L4T Ubuntu 24.04, a system Python 3.12, and a Blackwell GPU at compute capability 11.0 (sm_110) [1]. Three consequences of that stack drive every verdict in this report.

Memory stops being the interesting constraint. Because the 122 GB is unified rather than a dedicated VRAM pool, a 24 GB model is a scheduling and bandwidth question rather than a capacity wall, and several models can be resident simultaneously. What unified memory does not do is make compiled kernels portable.

CUDA-enabled torch for aarch64 has to come from NVIDIA rather than PyPI. The aarch64 torch wheels published on PyPI are CPU-only builds — the 2.6.0 aarch64 wheel declares no `nvidia-*` runtime dependencies whatsoever [2] — so a working Thor install must point at NVIDIA's own indexes. The Jetson AI Lab SBSA cu130 index carries torch 2.9 through 2.11 for cp312 aarch64 [3], and cu132 carries the 2.9.1 series across cp310 to cp314 [4]. This is a one-time platform decision that every candidate inherits; it is not a per-model risk, and it should be settled before any model work starts.

Python 3.12 collides with several upstream pins, and the fix is a per-model environment rather than a per-model patch. Hunyuan3D 2.1 pins numpy 1.24.4 and onnxruntime 1.16.3, and neither publishes a cp312 wheel; open3d 0.18 and pymeshlab 2022.2.post3 miss cp312 or aarch64 entirely. TRELLIS.2's own setup script answers this the way we should — a conda environment on Python 3.10 [7] — which also keeps the `cupy-cuda12x` and `bpy 4.0` pins satisfiable.

Finally, sm_110 is new enough that prebuilt attention kernels lag behind it. flash-attn publishes no wheels on PyPI at all, only an sdist [5], and the prebuilt binaries that do exist carry no sm_110 SASS, which is precisely the "no kernel image for device" failure reported against a Thor [6]. Any plan that assumes a pip-installed flash-attn on the Thor is wrong on day one.

## 2. Dependency availability on aarch64 and sm_110

The table below is the raw material for the Thor verdicts. Wheel counts come from PyPI's published file lists; nothing was installed and no project code was run, in line with the read-only constraint.

| Dependency | Linux aarch64 wheels | Consequence on the Thor |
|---|---|---|
| [torch](https://pypi.org/project/torch/) (PyPI) | yes, CPU-only build | install CUDA torch from NVIDIA's cu130/cu132 indexes [3][4] |
| [flash-attn](https://pypi.org/project/flash-attn/) | none (sdist only) | multi-hour source build; prebuilt wheels lack sm_110 SASS [5][6] |
| [xformers](https://pypi.org/project/xformers/) | none | source build, or fall back to torch SDPA |
| [spconv-cu120](https://pypi.org/project/spconv-cu120/) | none | source port; only TRELLIS v1 needs it |
| [kaolin](https://pypi.org/project/kaolin/) | none (sdist) | source port; only TRELLIS v1 needs it |
| [pytorch3d](https://pypi.org/project/pytorch3d/) | none | source port; blocks Material Anything |
| [nvdiffrast](https://github.com/NVlabs/nvdiffrast) | git/sdist only | compiles with the local nvcc; workable |
| [xatlas](https://pypi.org/project/xatlas/) | macOS arm64 only | C++ build; TripoSR and Hunyuan3D |
| [torchmcubes](https://github.com/Tatsy/torchmcubes), [PyMCubes](https://pypi.org/project/PyMCubes/) | none | small CUDA builds; TripoSR, InstantMesh |
| [pynanoinstantmeshes](https://pypi.org/project/pynanoinstantmeshes/), [gpytoolbox](https://pypi.org/project/gpytoolbox/) | none | builds; SF3D and SPAR3D |
| [numpy](https://pypi.org/project/numpy/) 1.24.4, [onnxruntime](https://pypi.org/project/onnxruntime/) 1.16.3 | aarch64 wheels, no cp312 | pin bump, or run Python 3.10 |
| [open3d](https://pypi.org/project/open3d/) 0.18, [pymeshlab](https://pypi.org/project/pymeshlab/) 2022.2 | aarch64 (open3d, no cp312), none (pymeshlab) | pin bump; pymeshlab 2025.x has cp312 aarch64 wheels |
| [triton](https://pypi.org/project/triton/), [bitsandbytes](https://pypi.org/project/bitsandbytes/), [cupy-cuda12x](https://pypi.org/project/cupy-cuda12x/) | yes, cp312 present | usable; verify sm_110 kernel coverage and a CUDA 12 runtime on a 13 driver |

Read as a group, the pattern is clean: the packages with no Linux aarch64 wheel are concentrated in exactly the two stacks we have already decided against — TRELLIS v1's kaolin/spconv/xformers chain and Material Anything's PyTorch3D. The sdist-only packages are buildable but slow. The cp312 gaps are ordinary constraint-file edits. Nothing on this list is a reason to abandon an entire candidate, and the two stacks that are expensive to port are the two we do not want anyway.

## 3. Licence register for shipped assets

Licence is a pipeline requirement here, not a footnote: every asset entering the library must carry its terms. The table separates project code from model weights, because on this list they frequently differ.

| Model | Code | Weights | Terms that touch shipped assets |
|---|---|---|---|
| TRELLIS.2 | MIT [7] | MIT, ungated [8] | clean; DINOv3 encoder terms apply [7] |
| TripoSR | MIT [14] | MIT, ungated [15] | clean |
| 3DTopia-XL | Apache-2.0 [30] | Apache-2.0 [31] | clean; training corpus is Objaverse-derived |
| Pixal3D | MIT [32] | MIT, ungated, but HF flags EU-disallowed and US-region [33] | third-party NOTICE obligations [32] |
| SF3D / SPAR3D | Stability AI Community Licence [25][28] | gated, licence "other" [26] | commercial use needs registration; >US$1M revenue needs an enterprise licence; "Powered by Stability AI" display; outputs owned by us [25] |
| Hunyuan3D 2.1 | Tencent Hunyuan 3D 2.1 Community [20] | gated, EU-disallowed [21] | EU/UK/South Korea excluded; output use restricted to the Territory; >1M MAU needs a separate licence; Notice file on distribution [20] |
| TRELLIS v1 | MIT [35] | MIT [36] | clean, but the stack does not build here |
| InstantMesh | Apache-2.0 [37] | Apache-2.0 | clean, but superseded |
| Nova3D and its MCP server | MIT [17][18] | not applicable — hosted service | output licence not published anywhere we could find |
| CHORD | Ubisoft ML, Research-Only Copyleft [44] | gated, same terms [45] | cannot ship commercial assets [44][46] |
| TexGaussian | no LICENSE file in the repository [42] | card says apache-2.0 [43] | ambiguous; treat as unusable until pinned |
| Material Anything | MIT [39] | Apache-2.0 [40] | clean |

Two dependency licences sit underneath the project licences and are easy to miss. nvdiffrast ships under the NVIDIA Source Code License in its "1-Way Commercial" variant, so commercial use is permitted [12]. nvdiffrec's licence says the work "only may be used or intended for use non-commercially", defined as research or evaluation only [13]. TRELLIS.2's reference pipeline pulls in both: nvdiffrast rasterizes and bakes textures during GLB export, while nvdiffrec is used for HDRI-lit preview rendering. In that stack the asset path is commercial and the preview path is not, which is a different and more precise statement than "TRELLIS.2 is MIT" — and it is the trap ComfyUI's own announcement flags when it removes those dependencies [10].

The MIT badge also does not cover the encoders. TRELLIS.2 conditions on a DINOv3 image encoder loaded through `transformers` [7], so Meta's DINOv3 licence — attribution and end-use conditions, no weapons or espionage use, no reverse engineering — travels with the pipeline even though the model's own weights are MIT. Pixal3D's repository documents the same situation in its NOTICE file [32]. Neither condition is a non-commercial restriction, but both belong on the checked list next to the weights licence.

## 4. Candidate assessments

### 4.1 TRELLIS.2 for PBR image-to-3D

Inputs are a single image for the shape stage and an optional text prompt for shape-conditioned texturing of an existing mesh. Outputs are GLB meshes with PBR material maps — albedo plus metallic-roughness in the reference pipeline, and normal plus ambient occlusion as well in the ComfyUI native path [10]. There is no B-rep output and no Gaussian-splat output. The method is a flow-matching transformer over structured O-Voxel latents [9].

Licensing is the cleanest on the list: MIT for the code [7] and MIT for the weights, ungated, with no region restriction [8].

Thor feasibility has two very different answers depending on which implementation you mean. The reference path installs torch 2.6.0+cu124, Python 3.10, flash-attn 2.7.3, nvdiffrast, nvdiffrec, CuMesh, O-Voxel and FlexGEMM [7]; on the Thor that is a multi-day build, a source-compiled flash-attn without sm_110 SASS, and a non-commercial renderer in the dependency set. The ComfyUI native path is the opposite: ComfyUI's core requirements contain none of flash-attn, nvdiffrast, nvdiffrec, triton, xformers, cumesh, flexgemm or o-voxel, and `comfy/ldm/trellis2/flexgemm.py` imports only torch [11]. What remains is a CUDA-enabled aarch64 torch from NVIDIA's index [3][4], the MIT weights ComfyUI republishes for the path [49], and a DINOv3 encoder from `transformers`.

Speed and memory figures are H100-only: roughly 3 s at 512³, 17 s at 1024³ and 60 s at 1536³, with at least 24 GB of memory and verification on A100 and H100 [8]. No Thor measurement exists. Our estimate — an inference, not a measurement — is that the Thor sits well below H100 on both dense throughput and memory bandwidth, so 1024³ should land in the tens-of-seconds to roughly 90-second range and 512³ should stay comfortably under a minute.

Determinism is handled well: the image-to-3D and texturing pipelines both take an explicit seed (default 42) and call `torch.manual_seed` [7].

Fit is the prop-maker role, and its shape-conditioned texturing also covers a slice of the texture role without a second environment. Verdict: **spike first**.

### 4.2 TripoSR as a licence-clean baseline

TripoSR takes an image and writes `mesh.obj` by default, with the format configurable, and `--bake-texture` adds a UV atlas and `texture.png` through xatlas [14]. It is vertex-coloured or baked-textured rather than PBR, and it produces no B-rep.

Both code and weights are MIT and ungated [14][15], which makes it the cheapest licence-clean entry on the list.

The dependency set is light: torchmcubes from git, xatlas (no Linux aarch64 wheel, so a C++ build), rembg and onnxruntime, and transformers 4.35 [14]. Nothing here needs a CUDA extension beyond the small marching-cubes build.

The 6 GB and sub-500 ms figures are the project's own A100 and default-options numbers [14][16]. The entry script exposes no seed argument, so determinism requires seeding torch externally and recording the value ourselves.

Fit is the fast prop baseline and, more importantly, the plumbing exercise: it is the cheapest way to force the scheduler's provenance record, seed handling and mesh-cache format into existence before a heavier model lands. Verdict: **adopt as the baseline, in parallel with the spike**.

### 4.3 Nova3D and its MCP server

Nova3D's client repository is a Flutter application; its AI path has a model write Blender construction code, run it headlessly, and return a structured GLB with named parts, hierarchy and real joints [17]. The MCP server exists and is worth knowing about: the repository is `RareSense/nova3d-mcp`, MIT-licensed, archived on 2026-06-28 and folded into the monorepo's `mcp/` directory, and the `nova3d-mcp` package on PyPI is MIT [18][19]. Its tool surface is `nova3d_setup`, `nova3d_status`, `nova3d_login`, `nova3d_logout`, `generate_3d`, `regenerate_part`, `add_part` and `articulate_model` [18].

The decisive detail for our use is that this server is a thin HTTP client for a hosted service: the package points at `https://nova3d.xyz/api` and receives hosted GLB URLs, and the Blender execution happens server-side rather than on the client [19]. It therefore adds a cloud dependency and a per-credit cost rather than moving generation onto the Thor.

Licensing is MIT for the code we could read [17][18], but the licence that would govern generated assets lives in service terms we could not locate — no reachable terms or pricing page — so the asset provenance record cannot be filled in honestly. Determinism is absent by construction: the package contains no seed parameter anywhere, and generation routes to paid hosted LLM tiers.

Fit is not the Thor but the interface. The MCP shape — a tool that returns named, structured parts rather than raw geometry — is a better pattern for our own CAD and prop tooling than anything the model families offer. Verdict: **skip for the Thor**; steal the interface pattern, and treat the service as a hosted fallback to be re-examined only once output terms exist in writing.

### 4.4 Hunyuan3D 2.x capability against licence constraints

Hunyuan3D 2.0's shape stage decodes an SDF on a regular grid and extracts the mesh with marching cubes [22]; 2.1 replaces the RGB texture model with PBR synthesis, generating albedo and metallic-roughness through multi-view diffusion at 6 to 12 views [23][20]. Outputs are meshes plus PBR maps.

Capability is the strongest on the list, and the licence is the obstacle. The Tencent Hunyuan 3D 2.1 Community Licence defines a Territory that excludes the EU, the UK and South Korea, restricts output use to that Territory, requires a separate licence above one million monthly active users, and requires the Notice file to accompany distributions [20][21]. Our US-only distribution would technically sit inside the Territory, but a revenue-dependent trigger and output-territory wording make this a legal-review item rather than a scheduler entry.

The stack also fights the platform. Hunyuan3D 2.1 needs a custom CUDA rasterizer built in-tree, and its pins (numpy 1.24.4, onnxruntime 1.16.3, pymeshlab 2022.2.post3, bpy 4.0, cupy) all predate good cp312 aarch64 support [20]. Memory is a non-issue at 10 GB for shape, 21 GB for texture and 29 GB combined [20], but no seed is exposed in the sample scripts. Finally, the strongest Hunyuan — 2.5 with its LATTICE shape model — has no released weights at all and exists only as a hosted product [24].

Verdict: **skip for now**, revisited only if the licence review clears and TRELLIS.2's PBR fidelity proves insufficient for the prop-maker role.

### 4.5 Stable Fast 3D and SPAR3D

SF3D takes an image and returns a UV-unwrapped textured GLB with metallic and roughness predictions, which is the format a game renderer wants [25][27]. SPAR3D adds a point-cloud stage that yields an editable point cloud alongside the mesh [28][29]. Neither produces a per-texel PBR set the way TRELLIS.2 or Hunyuan3D do — SF3D's material parameters are per object.

The licence is the Stability AI Community Licence for code and weights, with the weights gated on Hugging Face [25][26]. It permits research and non-commercial use freely, permits limited commercial use provided we register with Stability AI, and cuts off above USD 1,000,000 in annual revenue, after which an enterprise licence is required. Distribution carries obligations that are easy to miss: the Stability notice must be retained in a "Notice" file and "Powered by Stability AI" displayed in the product [25]. Outputs remain ours [25], which is the clause that makes it usable.

Feasibility is middling. Both projects build an in-repo CUDA texture baker and a C++ UV unwrapper, and depend on `pynanoinstantmeshes` and `gpytoolbox`, none of which have Linux aarch64 wheels [25][28]. That is two source builds plus a C++ library.

Speed and memory are the ~6 GB and "under one second" figures, with no GPU named for the latter [25]; SPAR3D, in the same family, defaults to 10.5 GB and falls to roughly 7 GB in low-VRAM mode [28]. Neither entry script exposes a seed.

Fit is the prop-maker role with the best quality-per-second on the list, and the paperwork is a day of work rather than a blocker. Verdict: **spike second**, with the Stability registration started in parallel because it has a lead time.

### 4.6 3DTopia-XL and Pixal3D

3DTopia-XL is the only shortlisted model that takes text as a first-class input and emits a PBR GLB with geometry, texture and material in one pass; it exposes a `seed` configuration key and an `export_glb` option, and claims roughly five seconds per asset [30]. Code and weights are Apache-2.0, which is as clean as MIT for our purposes [30][31]. The build cost is the problem: it depends on nvdiffrast, PyMCubes with no aarch64 wheel, libigl, and a Triton 2.1.0 pin that conflicts with a CUDA 13 toolchain [30].

Pixal3D is a single-image, pixel-aligned generator producing GLB meshes with PBR textures at 1536 by default or 1024 in low-VRAM mode, with separate multi-view weights available [32][34]. Its code and weights are MIT [32][33], though Hugging Face flags the weights as EU-disallowed and US-region [33] — a distribution constraint we can live with but must record. The encouraging operational detail is that it supports an `ATTN_BACKEND=sdpa` switch, the same escape hatch that makes the ComfyUI path viable on sm_110 [32].

Verdicts: 3DTopia-XL **spike later**, because text-to-3D is a capability we do not otherwise have and the licence is clean; Pixal3D **evaluate alongside TRELLIS.2** inside the same ComfyUI environment, since it costs one extra model download and one extra set of weights.

### 4.7 TRELLIS v1 and InstantMesh

TRELLIS v1 is MIT in code and weights [35][36] and outputs a textured GLB plus a `.ply` Gaussian-splat file, at 16 GB minimum and verified on A100 and A6000 [35]. On the Thor it is not viable as written: the setup script requires kaolin, spconv-cu120, xformers and flash-attn, none of which have Linux aarch64 wheels, on top of a torch 2.4.0/cu118 pin [35]. The splat output also has no consumer in a Blender and Cycles scene graph.

InstantMesh is Apache-2.0 in code and weights [37][38]. It generates multi-view diffusion images with zero123++ and then reconstructs a sparse-view mesh, exporting an OBJ with vertex colours by default and requiring `--export_texmap` for a texture map at a much higher cost [37]. It needs nvdiffrast, PyMCubes without an aarch64 wheel, bitsandbytes whose sm_110 kernel coverage is unverified, and diffusers 0.20.2 [37].

Verdicts: **skip both**. TRELLIS v1's dependency stack is not worth porting for an output format the world engine does not consume, and InstantMesh is superseded by TRELLIS.2 on both quality and dependency count.

### 4.8 Texture and material models

TRELLIS.2's shape-conditioned texturing is the pragmatic choice for the texture role: MIT, already resident in the same environment as the prop path, and it introduces no new compiled dependency [7][10]. It is the first thing to adopt.

Material Anything is the stronger tool when the mesh already exists. Its code is MIT, its estimator weights are Apache-2.0, and it produces albedo, roughness, metallic and bump maps at 1024² for any mesh [39][40][41]. Its obstacle is PyTorch3D, which has no Linux aarch64 wheel and would need a source port [41]. Verdict: **spike later**, once that port is worth doing for other reasons.

CHORD is the strongest PBR estimator we found and the least usable: Ubisoft's Machine Learning Licence is Research-Only Copyleft, which forbids commercial use and imposes copyleft obligations [44][45][46]. Verdict: **skip for shipped assets**; reference material only.

TexGaussian generates high-quality PBR from text for a given mesh, and its Hugging Face card says apache-2.0, but the repository carries no LICENSE file at all and the pipeline needs a modified diff-gaussian-rasterization plus nvdiffrast [42][43]. Verdict: **skip** — licence ambiguity plus build cost.

MatLat, VideoMatGen and Texture Space Material Diffusion are the papers worth watching for text-conditioned PBR generation [47][48], but we could not find local weights for any of them, so none is schedulable today.

## 5. Determinism and provenance records

Seed exposure is uneven and worth stating plainly. TRELLIS.2 takes a seed in both the image-to-3D and texturing pipelines, defaulting to 42 [7]. 3DTopia-XL exposes a seed configuration key [30]. InstantMesh exposes a `sample_seed` [37]. TripoSR, SF3D, SPAR3D and Hunyuan3D expose no seed argument at all, so the scheduler would have to seed torch externally and record the value itself [14][25][28][20]. Nova3D's MCP surface has no seed anywhere, and routes generation to hosted LLM tiers [19].

Seeded is not the same as bit-identical. Rasterization with atomics, attention kernels that select different strategies at runtime, and non-deterministic CUDA reductions mean byte-for-byte reproduction is not something we should promise for any of these models. The honest unit of reproducibility is the recipe: prompt, seed, model identifier, weights revision hash, resolution, sampler settings and environment revision. Bit-exact reproducibility remains available only in the parametric CAD path, which is a further argument for keeping CAD parts on code rather than on a diffusion model.

That suggests the provenance record builder-ide needs. Every asset should carry the prompt, the model and weights revision, the seed, the sampling parameters, the output format, the licence string for the specific weights and dependency set used, and the environment revision of the Thor that produced it. The mesh file itself is the artifact of record, and a re-run should be expected to reproduce the same recipe rather than the same bytes.

## 6. Role fit and scheduler integration

Mapping the roles in the vision to what these models can actually do: the prop-maker role takes image-to-3D, where TRELLIS.2, SF3D, SPAR3D, 3DTopia-XL and Pixal3D all qualify and TripoSR is the fast fallback. The texture and material role takes TRELLIS.2's shape-conditioned texturing first and Material Anything later. The CAD part role stays on parametric code, because no shortlisted model emits a B-rep or STEP and none will be trustworthy for a bolt that has to fit. The character role stays on recipe and rig, because none of these models produce skinned or rigged characters. The scene role stays with the world engine assembling props into scenes. Gaussian splats appear only in TRELLIS v1, and nothing in the Blender and Cycles path consumes them.

For the scheduler, each model family wants its own environment, because torch versions, compiled extensions and licence conditions differ per family; that maps cleanly onto the hot/warm/cold lifecycle, where a model is hot when its environment is resident on the GPU, and the night's jobs are batched by model so the scheduler is not thrashing environments. The licence field should be written by the model registry rather than by the job that happens to call it, so that every asset inherits the right terms without the job author having to remember them.

## 7. Claims checked

The claims from the second idea list, checked against each project's own evidence and against the Thor's facts.

| Claim | Verdict | Evidence |
|---|---|---|
| Nova3D has an MCP server exposing structured geometry tools | **True** | `RareSense/nova3d-mcp`, MIT, archived 2026-06-28, published as MIT `nova3d-mcp` 0.4.0, with tools including `generate_3d`, `regenerate_part`, `add_part`, `articulate_model` [18][19] |
| …and it compiles parametric programs to GLB deterministically | **False as stated** | The server is a thin client for the hosted API at `nova3d.xyz/api`; the Blender execution runs server-side, the package exposes no seed, and no determinism guarantee is documented [19] |
| TRELLIS.2 is a 4B multimodal model producing PBR meshes | **True** | 4B flow-matching transformer with image conditioning and text-conditioned texturing, emitting GLB with albedo and metallic-roughness, and normal plus AO in the native ComfyUI path [8][9][10] |
| TRELLIS.2 relies on nvdiffrast | **True upstream, not in the recommended path** | The reference setup installs nvdiffrast and nvdiffrec [7]; nvdiffrast rasterizes during GLB export and nvdiffrec handles HDRI-lit preview renders. ComfyUI's native implementation needs neither [10][11] |
| TRELLIS.2 is "sub-minute on the Thor" | **Unverified** | The published ladder is H100-only — 3 s at 512³, 17 s at 1024³, 60 s at 1536³, at least 24 GB, verified on A100 and H100 [8]. No Thor benchmark exists, and flash-attn's prebuilt wheels lack sm_110 SASS [5][6] |
| TripoSR and SF3D run in ~6 GB and under 500 ms on the Thor | **False as stated, unverified for the Thor** | Both figures are the projects' own default-option numbers, with TripoSR's sub-0.5 s explicitly an A100 measurement [14][16] and SF3D's "under one second" naming no GPU [25]. SPAR3D in the same family defaults to 10.5 GB [28] |
| Hunyuan3D 2.0 (DiT) has clean topology and multi-view texturing | **Partly true** | Multi-view texturing is real and becomes PBR in 2.1 [23]; but the 2.0 shape stage decodes an SDF grid and extracts with marching cubes [22], so the topology is a consistent grid mesh rather than artist-authored quads |
| Hunyuan3D 2.0 "maps beautifully to the Thor" | **Not supported** | Capability fits the memory envelope at 10/21/29 GB [20]; the stack does not — no cp312 wheels for numpy 1.24.4 or onnxruntime 1.16.3, no aarch64 wheel for pymeshlab 2022.2.post3, an in-tree custom CUDA rasterizer [20] — and the weights are under a Community Licence that excludes the EU, UK and South Korea and adds a >1M MAU trigger [20][21] |

Two of the four claims are simply transplanted datacenter numbers, and one quietly converts a hosted service into a local capability. The sub-claims that are true are true for reasons worth keeping: the MCP server is real and worth studying, and TRELLIS.2 really is a 4B model that really does emit PBR.

## 8. Spike order and selection rationale

Spike TRELLIS.2 first, through the ComfyUI native path, for four reinforcing reasons. It is the only shortlisted model that is simultaneously MIT in code and MIT in weights with no region restriction [7][8]. It is the only one that emits real PBR maps, which is what the renderer needs [10]. It is the only path on the list that requires no compiled CUDA extension, which removes the entire sm_110 build risk from the critical path [11]. And it exposes a seed, so the provenance work starts on solid ground [7].

The full disposition, with the role each model would take in the pipeline:

| Candidate | Role in the pipeline | Verdict |
|---|---|---|
| TRELLIS.2 via ComfyUI native | prop maker; shape-conditioned texture | spike first |
| TripoSR | fast prop baseline; provenance plumbing | adopt in parallel |
| 3DTopia-XL | text-to-3D props | spike later |
| SF3D / SPAR3D | textured props, best quality-per-second | spike second, if TRELLIS.2 disappoints |
| Pixal3D | pixel-aligned props | evaluate alongside TRELLIS.2 |
| Material Anything | PBR on an existing mesh | spike later, after a PyTorch3D port |
| Hunyuan3D 2.x | PBR props with full training code | skip pending licence review |
| Nova3D | hosted, named-part generation | skip for the Thor; reuse the interface pattern |
| TRELLIS v1, InstantMesh | superseded mesh generation | skip |
| CHORD, TexGaussian | PBR estimation and materials | skip for shipped assets |

Time-box the spike to two days and measure four things on the box rather than on a spec sheet: that the 4B weights load and run under a CUDA-enabled aarch64 torch from NVIDIA's index [3][4]; wall-clock at 512³ and 1024³ so the scheduler's throughput table has Thor numbers in it; PBR fidelity after a round trip through Blender 4.2, which is the real acceptance test for our renderer; and peak unified-memory use at batch size one and above, since that is what determines how many models can stay hot.

In parallel on the same day, stand up TripoSR. It is hours of work, its licences are clean, and it forces the scheduler plumbing — seed handling, provenance record, mesh cache, licence inheritance — that every subsequent model will need anyway.

Then order the rest by cost of regret: 3DTopia-XL next, because text-to-3D is a capability nothing else on the list provides and its licence is clean; SF3D after that if TRELLIS.2's PBR fidelity or throughput disappoints, with the Stability registration started early because it has a lead time we do not control; Pixal3D evaluated inside the same ComfyUI environment since it is one extra weights download; Material Anything once the PyTorch3D port has a reason to exist; Hunyuan3D only after a licence review; and Nova3D only as a hosted fallback with written terms.

Do not schedule against the published numbers. Fill in the scheduler's throughput table from measurements on this box, and record the measurement alongside each model's provenance entry so the next person does not have to re-derive it.

## Sources

1. NVIDIA, JetPack SDK Downloads and Release Notes — https://developer.nvidia.com/embedded/jetson-linux
2. PyPI, torch project file list (aarch64 wheels are CPU-only builds) — https://pypi.org/project/torch/
3. NVIDIA Jetson AI Lab, SBSA cu130 index (torch 2.9–2.11, cp312 aarch64) — https://pypi.jetson-ai-lab.io/sbsa/cu130/torch/
4. NVIDIA Jetson AI Lab, SBSA cu132 index (torch 2.9.1, cp310–cp314 aarch64) — https://pypi.jetson-ai-lab.io/sbsa/cu132/torch/
5. PyPI, flash-attn (sdist only, no wheels) — https://pypi.org/project/flash-attn/
6. Dao-AILab, flash-attention issue #2220 — "no kernel image is available for execution on the device" on a Thor — https://github.com/Dao-AILab/flash-attention/issues/2220
7. Microsoft, TRELLIS.2 repository (MIT licence, setup.sh dependency flags, seeded pipelines) — https://github.com/microsoft/TRELLIS.2
8. Hugging Face, microsoft/TRELLIS.2-4B model card (MIT weights, H100 timings, 24 GB requirement) — https://huggingface.co/microsoft/TRELLIS.2-4B
9. TRELLIS.2 paper, "Native and Compact Structured Latents for 3D Generation" — https://arxiv.org/abs/2512.14692
10. ComfyUI, "Trellis.2 and Pixal3D Are Now Native in ComfyUI", 2026-08-31 — https://blog.comfy.org/p/trellis2-and-pixal3d-are-now-native
11. ComfyUI repository (core requirements; `comfy/ldm/trellis2/flexgemm.py`) — https://github.com/comfyanonymous/ComfyUI
12. NVlabs, nvdiffrast LICENSE.txt (NVIDIA Source Code License, 1-Way Commercial) — https://github.com/NVlabs/nvdiffrast/blob/main/LICENSE.txt
13. NVlabs, nvdiffrec LICENSE.txt ("only may be used or intended for use non-commercially") — https://github.com/NVlabs/nvdiffrec/blob/main/LICENSE.txt
14. VAST AI Research, TripoSR repository (MIT licence, A100 timing, 6 GB figure, export options, requirements) — https://github.com/VAST-AI-Research/TripoSR
15. Hugging Face, stabilityai/TripoSR model card (MIT weights) — https://huggingface.co/stabilityai/TripoSR
16. TripoSR technical report — https://arxiv.org/abs/2403.02151
17. RareSense, Nova3D repository (MIT licence, Blender construction pipeline) — https://github.com/RareSense/Nova3D
18. RareSense, nova3d-mcp repository (MIT licence, archived, tool list) — https://github.com/RareSense/nova3d-mcp
19. PyPI, nova3d-mcp 0.4.0 (MIT, hosted API client at nova3d.xyz/api) — https://pypi.org/project/nova3d-mcp/
20. Tencent Hunyuan, Hunyuan3D-2.1 repository (Community Licence terms, VRAM figures, custom_rasterizer, requirements) — https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1
21. Hugging Face, Tencent-Hunyuan/Hunyuan3D-2.1 (gated, EU-disallowed) — https://huggingface.co/Tencent-Hunyuan/Hunyuan3D-2.1
22. Hunyuan3D 2.0 paper (SDF decoding and marching cubes) — https://arxiv.org/abs/2501.12202
23. Hunyuan3D 2.1 paper (PBR multi-view texture synthesis) — https://arxiv.org/abs/2506.15442
24. Tencent Hunyuan, Hunyuan3D-2 repository (2.5 as a hosted product, no released weights) — https://github.com/Tencent-Hunyuan/Hunyuan3D-2
25. Stability AI, stable-fast-3d repository and Community Licence (registration, revenue threshold, Notice, output ownership) — https://github.com/Stability-AI/stable-fast-3d
26. Hugging Face, stabilityai/stable-fast-3d (gated, licence "other") — https://huggingface.co/stabilityai/stable-fast-3d
27. SF3D paper (UV unwrapping, illumination disentanglement) — https://arxiv.org/abs/2408.00653
28. Stability AI, stable-point-aware-3d repository (10.5 GB default, 7 GB low-VRAM, requirements) — https://github.com/Stability-AI/stable-point-aware-3d
29. SPAR3D paper — https://arxiv.org/abs/2501.04689
30. 3DTopia, 3DTopia-XL repository (Apache-2.0, seed and export_glb options, dependency list) — https://github.com/3DTopia/3DTopia-XL
31. Hugging Face, 3DTopia/3DTopia-XL (Apache-2.0 weights) — https://huggingface.co/3DTopia/3DTopia-XL
32. TencentARC, Pixal3D repository (MIT licence, NOTICE, low-VRAM and sdpa switches) — https://github.com/TencentARC/Pixal3D
33. Hugging Face, TencentARC/Pixal3D (MIT weights, EU-disallowed, region:us) — https://huggingface.co/TencentARC/Pixal3D
34. Pixal3D paper (pixel-aligned generation, back-projection) — https://arxiv.org/abs/2605.10922
35. Microsoft, TRELLIS repository (v1 setup requirements, 16 GB, splat output) — https://github.com/microsoft/TRELLIS
36. Hugging Face, microsoft/TRELLIS-image-large (MIT weights) — https://huggingface.co/microsoft/TRELLIS-image-large
37. TencentARC, InstantMesh repository (Apache-2.0, OBJ and --export_texmap, requirements) — https://github.com/TencentARC/InstantMesh
38. InstantMesh paper — https://arxiv.org/abs/2404.07191
39. 3DTopia, MaterialAnything repository (MIT licence) — https://github.com/3DTopia/MaterialAnything
40. Hugging Face, xanderhuang/material_estimator (Apache-2.0 weights) — https://huggingface.co/xanderhuang/material_estimator
41. Material Anything paper (PBR maps for any mesh, PyTorch3D dependency) — https://arxiv.org/abs/2411.15138
42. ymxbj, TexGaussian repository (no LICENSE file, rasterizer dependencies) — https://github.com/ymxbj/TexGaussian
43. Hugging Face, ymxbj/TexGaussian (card licence: apache-2.0) — https://huggingface.co/ymxbj/TexGaussian
44. Ubisoft La Forge, ubisoft-laforge-chord repository (Ubisoft ML Licence, Research-Only Copyleft) — https://github.com/ubisoft/ubisoft-laforge-chord
45. Hugging Face, Ubisoft/ubisoft-laforge-chord (gated, research-only licence) — https://huggingface.co/Ubisoft/ubisoft-laforge-chord
46. CHORD paper — https://arxiv.org/abs/2509.09952
47. MatLat paper (material latent space for PBR texture generation) — https://arxiv.org/abs/2512.17302
48. Texture Space Material Diffusion paper — https://arxiv.org/abs/2609.37654
49. Hugging Face, Comfy-Org/TRELLIS.2 (MIT weights used by the native ComfyUI path) — https://huggingface.co/Comfy-Org/TRELLIS.2
