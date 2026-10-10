"""NFL Prediction Platform — local pipeline package.

Mirrors the Databricks PySpark notebooks using polars + deltalake so the full
medallion (Bronze -> Silver -> Gold) can be built and tested locally for $0,
then run on Databricks unchanged in logic.
"""

__version__ = "0.1.0"
