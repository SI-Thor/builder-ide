#!/usr/bin/env python3
"""Diagnose-only: patch the served prismarine-viewer bundle so the NaN
bounding-sphere warning prints which geometry it fired on. Run the
browser probe, then restore the original bundle (kept beside it)."""
import sys

path = sys.argv[1]
data = open(path, encoding="utf-8").read()
needle = "Computed radius is NaN."
i = data.find(needle)
assert i >= 0, "pattern not found"
# The minified call is: console.error('THREE....NaN values.',this)
# Find the end of that console.error call and splice a richer print in.
start = data.rfind("console.error", 0, i)
end = data.find(")", i)
assert start >= 0 and end >= 0, "call bounds not found"
original_call = data[start : end + 1]
replacement = (
    "console.error('NANGEO id='+this.id"
    "+' poscount='+(this.attributes.position?this.attributes.position.count:-1)"
    "+' indexcount='+(this.index?this.index.count:-1)"
    "+' userData='+(this.userData?JSON.stringify(Object.keys(this.userData)):'none')"
    "+' hasNaNSample='+(function(a,t,n){t=a?a.array:null;if(!t)return 'n/a';n=0;for(var k=0;k<t.length;k++){if(isNaN(t[k])){n=k;break}}return n})(this.attributes.position)"
    ")"
)
data = data[:start] + replacement + "," + original_call + data[end + 1 :]
open(path + ".nanbak", "w").write(open(path, encoding="utf-8").read())
open(path, "w", encoding="utf-8").write(data)
print("patched", path)
