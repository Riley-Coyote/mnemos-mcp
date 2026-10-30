"""Print the table in RESULTS.md from a bench.py results file."""
import json
import sys

r = json.load(open(sys.argv[1]))
print(r["machine"], "\nload", [round(x) for x in r["load_average"]], "vectors", r["vectors_read"], "wake rows", r["wake_rows"])
ops = ["recall_scope_words", "recall_scope_meaning", "recall_scope_total", "recall_all_words",
       "recall_all_meaning", "recall_all_total", "write", "wake"]
print(f"| {'op':22} |" + "|".join(f" {v:30} " for v in r["variants"]) + "|")
for op in ops:
    cells = []
    for v, d in r["variants"].items():
        x = d.get(op)
        cells.append(f" {x['median_ms']:>8} / {x['p95_ms']:>8} ms x{x.get('ratio_to_plain_median', 1.0):<5}" if x else " " * 32)
    print(f"| {op:22} |" + "|".join(cells) + "|")
for v in ("plain", "cipher-raw"):
    print(v, "snapshot", r["variants"][v]["snapshot"])
print("store", r["store"])
