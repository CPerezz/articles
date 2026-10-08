#!/usr/bin/env python3
"""Finding 3: how each store's code file holds the benchmark's test contracts.

Input: compactlatest codespan output per code file, written on the bench host by the study's
codespan.sh (jochemnet, state-actor) and recode-sa.sh (state-actor re-encoded):
codespan-<arm>.json (file totals, and per pattern group the encoded size and the 4 KB pages a
read of key and value touches) and codespan-<arm>.tsv (one line per maximum-size value: address,
group, encoded bytes, pages, value hash).

Prints JSON to stdout; the page reads it as data/report_data.json's provenance "code_layout".
Usage: collect_codespan.py <joc-prefix> <sa-prefix> <sa-recoded-prefix>
       e.g. collect_codespan.py codespan-joc-R14 codespan-sa-R14 codespan-sa-recoded
"""
import json
import sys

# The fixture patterns: first four bytes @ where the contract's own address sits (-1: nowhere).
GROUPS = ("615fff56@44", "00000000@12", "005b5b5b@-1")


def summary(prefix):
    d = json.load(open(prefix + ".json"))
    groups = {}
    for g in GROUPS:
        s = d["max_size_groups"][g]
        pages = s["pages_key_and_value"]
        groups[g] = {"n": s["n"], "bytes_min": s["encoded_value_bytes"]["min"],
                     "bytes_p50": s["encoded_value_bytes"]["p50"], "bytes_max": s["encoded_value_bytes"]["max"],
                     "pages_kv": sum(int(p) * c for p, c in pages.items()) / s["n"]}
    keep = ("file", "file_bytes", "keys", "pattern_dict_bytes", "stream_sha256", "value_raw_bytes",
            "value_encoded_bytes")
    return {k: d[k] for k in keep} | {"groups": groups}


def fixtures(prefix):
    out = {}
    for line in open(prefix + ".tsv"):
        addr, group, _, _, value_hash = line.rstrip("\n").split("\t")
        if group in GROUPS:
            out[addr] = (group, value_hash)
    return out


def real_max(prefix):
    """The maximum-size values that aren't test contracts: real mainnet code of the same size."""
    spans, pages = [], []
    for line in open(prefix + ".tsv"):
        _, group, span, pg, _ = line.rstrip("\n").split("\t")
        if group not in GROUPS:
            spans.append(int(span))
            pages.append(int(pg))
    spans.sort()
    pages.sort()
    return {"n": len(spans), "bytes_p50": spans[len(spans) // 2], "pages_p50": pages[len(pages) // 2]}


def main():
    joc, sa, rec = sys.argv[1:4]
    out = {"joc": summary(joc), "sa": summary(sa), "sa_recoded": summary(rec), "both": {},
           "joc_real_max": real_max(joc)}
    fj, fs = fixtures(joc), fixtures(sa)
    for g in GROUPS:
        j = {a for a, v in fj.items() if v[0] == g}
        s = {a for a, v in fs.items() if v[0] == g}
        both = j & s
        out["both"][g] = {"n_joc": len(j), "n_sa": len(s), "n_both": len(both),
                          "identical": sum(1 for a in both if fj[a] == fs[a])}
    json.dump(out, sys.stdout, indent=1, sort_keys=True)


if __name__ == "__main__":
    main()
