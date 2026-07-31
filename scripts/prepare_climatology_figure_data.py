"""Build figure-specific climatology parquets from the aggregate dataset."""

from pathlib import Path

import polars as pl

from style import PRECIP, SOLAR

REPO = Path(__file__).resolve().parents[1]
DERIVED = REPO / "data" / "derived"
LEADS = {"lead_1": 1, "lead_6": 6, "lead_12": 12, "lead_24": 24, "lead_48": 48}


def main() -> None:
    data = pl.read_parquet(DERIVED / "final_aggregates_climatology.parquet")
    base = data.filter(pl.col("debias") & pl.col("country").is_null())

    for track in ("track_a", "track_b"):
        headline = (
            base.filter(
                (pl.col("track") == track)
                & (pl.col("kind") == "skill_pct")
                & (pl.col("variable") != PRECIP)
                & pl.col("lead_scope").is_in(["h6_48", "h1_48", "h1_12"])
            )
            .select(
                "variable",
                "model",
                "obs_bucket",
                "lead_scope",
                pl.col("value").alias("skill"),
                "skill_se",
                pl.col("n_samples").alias("n"),
                "n_months",
            )
        )
        # All-condition Track A rows are definition-independent. Preserve the
        # released rows, including their historical monthly-jackknife snapshot.
        canonical = DERIVED / f"headline_skill_{track}.parquet"
        if track == "track_a" and canonical.exists():
            headline = pl.concat(
                [
                    headline.filter(pl.col("obs_bucket") != "all"),
                    pl.read_parquet(canonical).filter(pl.col("obs_bucket") == "all"),
                ]
            )
        headline = headline.sort("variable", "lead_scope", "obs_bucket", "model")
        out = DERIVED / f"headline_skill_{track}_climatology.parquet"
        headline.write_parquet(out)
        print("wrote", out, headline.height)

    solar_leads = (
        base.filter(
            (pl.col("track") == "track_a")
            & (pl.col("variable") == SOLAR)
            & (pl.col("kind") == "skill_pct")
            & pl.col("lead_scope").is_in(LEADS)
        )
        .with_columns(
            pl.col("lead_scope").replace_strict(LEADS).cast(pl.Int64).alias("lead_h")
        )
        .select(
            "model",
            "obs_bucket",
            "lead_h",
            pl.col("value").alias("skill"),
            "skill_se",
            pl.col("n_samples").alias("n"),
            "n_months",
        )
    )
    canonical_leads = DERIVED / "solar_lead_skill_track_a.parquet"
    if canonical_leads.exists():
        solar_leads = pl.concat(
            [
                solar_leads.filter(pl.col("obs_bucket") != "all"),
                pl.read_parquet(canonical_leads)
                .filter(pl.col("obs_bucket") == "all")
                .with_columns(pl.col("lead_h").cast(pl.Int64)),
            ]
        )
    solar_leads = solar_leads.sort("obs_bucket", "lead_h", "model")
    out = DERIVED / "solar_lead_skill_track_a_climatology.parquet"
    solar_leads.write_parquet(out)
    print("wrote", out, solar_leads.height)

    track_b_leads = (
        base.filter(
            (pl.col("track") == "track_b")
            & (pl.col("kind") == "skill_pct")
            & (pl.col("variable") != PRECIP)
            & pl.col("lead_scope").is_in(LEADS)
        )
        .with_columns(
            pl.col("lead_scope").replace_strict(LEADS).cast(pl.Int64).alias("lead_h")
        )
        .select(
            "model",
            "lead_h",
            "obs_bucket",
            pl.col("value").alias("skill"),
            "skill_se",
            "variable",
        )
    )
    track_b_leads = track_b_leads.sort("variable", "obs_bucket", "lead_h", "model")
    out = DERIVED / "track_b_lead_skill_climatology.parquet"
    track_b_leads.write_parquet(out)
    print("wrote", out, track_b_leads.height)

    # Solar month-by-month skill (fig9). Monthly rows carry the month label in
    # the country column, so they are excluded from `base` by construction and
    # have to be selected separately.
    monthly = data.filter(
        pl.col("debias")
        & (pl.col("kind") == "month")
        & (pl.col("variable") == SOLAR)
        & (pl.col("lead_scope") == "h1_48")
    )
    for track, stem in (
        ("track_a", "solar_monthly_skill_track_a"),
        ("track_b", "solar_monthly_skill_track_b"),
    ):
        frame = monthly.filter(pl.col("track") == track).select(
            "model",
            "obs_bucket",
            pl.col("country").alias("period_start"),
            pl.col("value").alias("skill"),
            pl.col("n_samples").alias("n"),
        )
        frame = frame.sort("period_start", "obs_bucket", "model")
        out = DERIVED / f"{stem}_climatology.parquet"
        frame.write_parquet(out)
        print("wrote", out, frame.height)

    solar_bias = base.filter(
        (pl.col("track") == "track_a")
        & (pl.col("variable") == SOLAR)
        & (pl.col("kind") == "bias")
        & (pl.col("lead_scope") == "lead_48")
    ).select(
        "model",
        "obs_bucket",
        pl.col("value").alias("bias"),
        pl.col("n_samples").alias("n"),
    )
    solar_bias = solar_bias.sort("obs_bucket", "model")
    out = DERIVED / "solar_bias_lead48_track_a_climatology.parquet"
    solar_bias.write_parquet(out)
    print("wrote", out, solar_bias.height)


if __name__ == "__main__":
    main()
