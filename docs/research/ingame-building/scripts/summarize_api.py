#!/usr/bin/env python3
"""summarize_api.py — turn .research/api/*.json into one fact table per repo.
Reads only the JSON captured by api_meta.sh; makes no network calls.
Usage: python3 .research/summarize_api.py
"""
import json, pathlib, re

API = pathlib.Path(__file__).parent / "api"
SLUGS = {
    "topviewai_topview-3d-builder": "topview-3d-builder",
    "thrixel_build-world": "build-world",
    "3DSceneAgent_Vibe3DScene": "Vibe3DScene",
    "FugthChat_MEP-SANDBOX-ENGINE": "MEP-SANDBOX-ENGINE",
    "GlaireDaggers_Open-World-Builder": "Open-World-Builder",
    "TorqueGameEngines_Torque3D": "Torque3D",
    "ProwlEngine_Prowl": "Prowl",
}

def last_page(link_file):
    p = API / link_file
    if not p.exists():
        return "?"
    txt = p.read_text(errors="replace")
    m = re.findall(r'page=(\d+)>;\s*rel="last"', txt)
    return m[-1] if m else ("1" if "rel=\"last\"" not in txt and txt.strip() else "1")

for slug, name in SLUGS.items():
    repo = json.loads((API / f"{slug}_repo.json").read_text())
    langs = json.loads((API / f"{slug}_lang.json").read_text())
    rels = json.loads((API / f"{slug}_releases.json").read_text())
    tags = json.loads((API / f"{slug}_tags.json").read_text())
    iss = json.loads((API / f"{slug}_issues.json").read_text())
    lang_total = sum(langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: -kv[1])[:6]
    print(f"### {name}  ({repo.get('full_name')})")
    print(f"  desc        : {repo.get('description')}")
    print(f"  homepage    : {repo.get('homepage')}")
    print(f"  created_at  : {repo.get('created_at')}   pushed_at: {repo.get('pushed_at')}  updated_at: {repo.get('updated_at')}")
    print(f"  stars/forks/watchers: {repo.get('stargazers_count')}/{repo.get('forks_count')}/{repo.get('subscribers_count')}")
    print(f"  size_kb     : {repo.get('size')}   primary_language: {repo.get('language')}")
    print(f"  license     : {(repo.get('license') or {}).get('spdx_id')} / {(repo.get('license') or {}).get('name')}")
    print(f"  archived    : {repo.get('archived')}  disabled: {repo.get('disabled')}  is_fork: {repo.get('fork')}")
    print(f"  default_branch: {repo.get('default_branch')}  open_issues_count(mixed): {repo.get('open_issues_count')}")
    print(f"  commits(approx): {last_page(f'{slug}_commits.link')}   contributors(approx): {last_page(f'{slug}_contributors.link')}")
    print(f"  issues      : open={iss['open_issues']} open_prs={iss['open_prs']} closed_issues={iss['closed_issues']}")
    print(f"  releases    : {len(rels)} -> " + ", ".join(f"{r.get('tag_name')}({str(r.get('published_at'))[:10]})" for r in rels[:5]))
    print(f"  tags(10 max): {[t.get('name') for t in tags[:10]]}")
    print(f"  languages   : " + ", ".join(f"{k} {v*100//lang_total}%" for k, v in top))
    print(f"  topics      : {repo.get('topics')}")
    print()
