"""Compute per-stock daily features from the raw `prices` table."""
import pandas as pd
from src.data.db import get_conn


def _compute(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("date").copy()
    df["pct_change_1d"] = df["close"].pct_change() * 100

    roll_252 = df["close"].rolling(252, min_periods=20)
    high_52w = roll_252.max()
    low_52w = roll_252.min()
    df["pct_from_52w_high"] = (df["close"] / high_52w - 1) * 100
    df["pct_from_52w_low"] = (df["close"] / low_52w - 1) * 100

    dma_50 = df["close"].rolling(50, min_periods=10).mean()
    dma_200 = df["close"].rolling(200, min_periods=20).mean()
    df["dist_50dma_pct"] = (df["close"] / dma_50 - 1) * 100
    df["dist_200dma_pct"] = (df["close"] / dma_200 - 1) * 100

    vol_20 = df["volume"].rolling(20, min_periods=5)
    vol_mean = vol_20.mean()
    vol_std = vol_20.std()
    df["vol_vs_20d_avg"] = df["volume"] / vol_mean
    df["vol_zscore_20d"] = (df["volume"] - vol_mean) / vol_std

    return df[[
        "symbol", "date", "pct_change_1d", "pct_from_52w_high", "pct_from_52w_low",
        "dist_50dma_pct", "dist_200dma_pct", "vol_vs_20d_avg", "vol_zscore_20d",
    ]]


def rebuild_features():
    con = get_conn()
    prices = con.execute("SELECT * FROM prices ORDER BY symbol, date").df()
    if prices.empty:
        print("No prices yet, run price_fetcher first.")
        con.close()
        return

    feats = (
        prices.groupby("symbol", group_keys=False)
        .apply(_compute)
        .dropna(subset=["pct_change_1d"])
    )

    con.execute("DELETE FROM features;")
    con.register("_f", feats)
    con.execute("INSERT INTO features SELECT * FROM _f;")
    con.unregister("_f")
    n = con.execute("SELECT COUNT(*) FROM features").fetchone()[0]
    con.close()
    print(f"Features rebuilt: {n} rows.")


if __name__ == "__main__":
    rebuild_features()
