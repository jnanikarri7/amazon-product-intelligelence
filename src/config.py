"""Configuration management for Amazon Product Intelligence System"""

import os
from pathlib import Path
from typing import Any, Dict, Optional
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError


class DiscoveryFilters(BaseModel):
    price_min: int = Field(ge=0)
    price_max: int = Field(ge=0)
    sales_rank_max: int = Field(gt=0)
    new_offer_count_max: int = Field(ge=0)
    rating_min: int = Field(ge=0, le=50)
    review_count_max: int = Field(ge=0)
    review_count_min: int = Field(ge=0, default=10)


class DiscoveryConfig(BaseModel):
    domain_id: int = Field(default=1)
    filters: DiscoveryFilters
    max_results: int = Field(default=100, le=10000)
    exclude_categories: Optional[list[int]] = None
    root_category: Optional[int] = None


class ScoringWeights(BaseModel):
    demand: float = Field(ge=0, le=1)
    competition: float = Field(ge=0, le=1)
    margin: float = Field(ge=0, le=1)
    simplicity: float = Field(ge=0, le=1)
    price_stability: float = Field(ge=0, le=1)


class ScoringThresholds(BaseModel):
    sales_rank_excellent: int
    sales_rank_good: int
    sales_rank_acceptable: int
    seller_count_low: int
    seller_count_medium: int
    seller_count_high: int
    review_barrier_high: int
    review_barrier_medium: int
    review_barrier_low: int
    price_ideal_min: float
    price_ideal_max: float
    simple_review_max: int
    moderate_review_max: int
    stable_cv_max: float
    moderate_cv_max: float


class ScoringConfig(BaseModel):
    weights: ScoringWeights
    thresholds: ScoringThresholds


class ExportConfig(BaseModel):
    csv_path: str
    json_path: str
    top_n: int = Field(default=50)


class DatabaseConfig(BaseModel):
    path: str


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


class AppConfig(BaseModel):
    discovery: DiscoveryConfig
    scoring: ScoringConfig
    export: ExportConfig
    database: DatabaseConfig
    logging: LoggingConfig


class Config:
    """Application configuration manager"""

    def __init__(self, config_path: Optional[str] = None, env_path: Optional[str] = None):
        self.project_root = Path(__file__).parent.parent

        if env_path:
            load_dotenv(env_path)
        else:
            load_dotenv(self.project_root / ".env")

        self.keepa_api_key = os.getenv("KEEPA_API_KEY")
        if not self.keepa_api_key:
            raise ValueError("KEEPA_API_KEY not found in environment variables")

        if config_path:
            config_file = Path(config_path)
        else:
            config_file = self.project_root / "config.yaml"

        if not config_file.exists():
            raise FileNotFoundError(f"Config file not found: {config_file}")

        with open(config_file, "r") as f:
            config_dict = yaml.safe_load(f)

        try:
            self.app = AppConfig(**config_dict)
        except ValidationError as e:
            raise ValueError(f"Invalid configuration: {e}")

        self._validate_scoring_weights()

    def _validate_scoring_weights(self):
        """Ensure scoring weights sum to 1.0"""
        weights = self.app.scoring.weights
        total = weights.demand + weights.competition + weights.margin + weights.simplicity + weights.price_stability

        if not (0.99 <= total <= 1.01):
            raise ValueError(f"Scoring weights must sum to 1.0, got {total}")

    @property
    def database_path(self) -> Path:
        """Get absolute database path"""
        db_path = Path(self.app.database.path)
        if not db_path.is_absolute():
            db_path = self.project_root / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return db_path

    @property
    def csv_path(self) -> Path:
        """Get absolute CSV export path"""
        csv_path = Path(self.app.export.csv_path)
        if not csv_path.is_absolute():
            csv_path = self.project_root / csv_path
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        return csv_path

    @property
    def json_path(self) -> Path:
        """Get absolute JSON export path"""
        json_path = Path(self.app.export.json_path)
        if not json_path.is_absolute():
            json_path = self.project_root / json_path
        json_path.parent.mkdir(parents=True, exist_ok=True)
        return json_path

    def get_discovery_filters(self) -> Dict[str, Any]:
        """Convert discovery filters to Keepa API format"""
        filters = self.app.discovery.filters

        keepa_filters = {
            "current_SALES": f"0-{filters.sales_rank_max}",
            "current_AMAZON": f"{filters.price_min}-{filters.price_max}",
            "current_COUNT_NEW": f"0-{filters.new_offer_count_max}",
            "rating": f"{filters.rating_min}-50",
            "count_reviews": f"{filters.review_count_min}-{filters.review_count_max}",
        }

        return keepa_filters


if __name__ == "__main__":
    config = Config()
    print(f"Keepa API Key: {'*' * 20}{config.keepa_api_key[-4:]}")
    print(f"Domain ID: {config.app.discovery.domain_id}")
    print(f"Database: {config.database_path}")
    print(f"Discovery filters: {config.get_discovery_filters()}")
