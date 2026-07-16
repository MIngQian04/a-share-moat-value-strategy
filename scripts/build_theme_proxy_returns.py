# Allow running this file directly from the project root, e.g.
# python scripts/run_xxx.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pathlib import Path
import pandas as pd


FINAL_PATH = Path(
    "data/processed/selection/final_candidates.csv"
)

RETURNS_PATH = Path(
    "data/processed/selection/stock_return_matrix.csv"
)

OUT_PATH = Path(
    "data/processed/research/theme_proxy_returns.parquet"
)

OUT_MAP_PATH = Path(
    "data/processed/research/theme_proxy_map.csv"
)


def main():

    final = pd.read_csv(FINAL_PATH)
    returns = pd.read_csv(RETURNS_PATH)

    returns["trade_date"] = pd.to_datetime(
        returns["trade_date"]
    )

    returns = (
        returns
        .set_index("trade_date")
        .sort_index()
    )

    rank1 = (
        final[
            final["assembly_rank"] == 1
        ]
        [
            [
                "theme",
                "ts_code",
            ]
        ]
        .drop_duplicates("theme")
        .sort_values("theme")
    )

    rows = []
    proxy_returns = {}

    for _, row in rank1.iterrows():

        theme = str(row["theme"])
        code = str(row["ts_code"])

        if code not in returns.columns:

            print(
                "missing:",
                theme,
                code,
            )

            continue

        proxy_returns[theme] = (
            pd.to_numeric(
                returns[code],
                errors="coerce",
            )
        )

        rows.append({
            "theme": theme,
            "proxy_ts_code": code,
        })

    proxy_df = (
        pd.DataFrame(proxy_returns)
        .sort_index()
    )

    map_df = pd.DataFrame(rows)

    OUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    proxy_df.to_parquet(
        OUT_PATH
    )

    map_df.to_csv(
        OUT_MAP_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    print(
        "\n===== THEME PROXY MAP ====="
    )

    print(
        map_df.to_string(index=False)
    )

    print(
        "\n===== PROXY RETURNS INFO ====="
    )

    print(
        "shape:",
        proxy_df.shape,
    )

    print(
        "date min:",
        proxy_df.index.min(),
    )

    print(
        "date max:",
        proxy_df.index.max(),
    )

    print(
        "\n===== COVERAGE ====="
    )

    for theme in proxy_df.columns:

        valid = (
            proxy_df[theme]
            .dropna()
        )

        print(
            theme,
            "n=",
            len(valid),
            "start=",
            valid.index.min()
            if not valid.empty
            else None,
            "end=",
            valid.index.max()
            if not valid.empty
            else None,
        )

    print(
        "\nsaved:",
        OUT_PATH,
    )

    print(
        "saved:",
        OUT_MAP_PATH,
    )


if __name__ == "__main__":
    main()
