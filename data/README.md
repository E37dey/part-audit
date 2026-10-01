# data/

Only `sample/` is part of the repository: a small synthetic demo set (ABC parts, mock ERP, ground truth)
so the tool can be tried without downloading anything. The dev/test sets are rebuilt with
`tools/build_dataset.py` (see the main README); they are a few hundred MB and are not committed.

`sample/` was built with:

    python tools/build_dataset.py --abc RAW/abc0 --n-base 30 --seed 7 --out data/sample \
        --rates A=0.1,B=0.1,C=0.1,D=0.1,E=0.15,F=0.15 --hn name=0.1,material=0.1,thickness=0.1,mirror=0.1

ABC Dataset models: MIT licence for the dataset, model rights belong to their creators; internal use only.
