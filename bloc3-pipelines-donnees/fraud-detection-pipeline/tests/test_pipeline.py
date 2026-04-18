"""
Tests unitaires du pipeline.
On teste surtout la validation des données et le preprocessing.
"""
import sys, os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.data_quality.validators import DataQualityValidator
from src.ml.preprocessing import build_preprocessing_pipeline, FeatureEngineer


class TestDataQuality:

    def setup_method(self):
        self.validator = DataQualityValidator()
        self.good_txn = {
            "trans_num": "TXN001",
            "amt": 125.50,
            "cc_num": "4111111111111111",
            "merchant": "Test Merchant",
            "category": "grocery_pos",
            "lat": 40.7128,
            "long": -74.0060,
            "merch_lat": 40.7200,
            "merch_long": -74.0100,
            "city_pop": 8336817,
            "unix_time": 1371816893,
        }

    def test_valid_transaction(self):
        ok, errors = self.validator.validate_transaction(self.good_txn)
        assert ok is True
        assert len(errors) == 0

    def test_missing_field(self):
        txn = self.good_txn.copy()
        del txn["trans_num"]
        ok, _ = self.validator.validate_schema(txn)
        assert ok is False

    def test_negative_amount(self):
        txn = self.good_txn.copy()
        txn["amt"] = -50.0
        ok, _ = self.validator.validate_business_rules(txn)
        assert ok is False

    def test_zero_amount(self):
        txn = self.good_txn.copy()
        txn["amt"] = 0
        ok, _ = self.validator.validate_business_rules(txn)
        assert ok is False

    def test_huge_amount(self):
        txn = self.good_txn.copy()
        txn["amt"] = 99999
        ok, _ = self.validator.validate_business_rules(txn)
        assert ok is False

    def test_bad_coordinates(self):
        txn = self.good_txn.copy()
        txn["lat"] = 999.0
        ok, _ = self.validator.validate_business_rules(txn)
        assert ok is False

    def test_short_cc_number(self):
        txn = self.good_txn.copy()
        txn["cc_num"] = "123"
        ok, _ = self.validator.validate_business_rules(txn)
        assert ok is False

    def test_valid_prediction(self):
        ok, _ = self.validator.validate_prediction(0.85)
        assert ok is True

    def test_prediction_out_of_range(self):
        ok, _ = self.validator.validate_prediction(1.5)
        assert ok is False

    def test_prediction_none(self):
        ok, _ = self.validator.validate_prediction(None)
        assert ok is False


class TestPreprocessing:

    def test_feature_engineer_shape(self):
        import numpy as np
        fe = FeatureEngineer()
        sample = [[100.0, 40.71, -74.00, 8000000, 1371816893, 40.72, -74.01]]
        result = fe.transform(sample)
        # On attend 6 features en sortie
        assert result.shape == (1, 6)

    def test_pipeline_builds(self):
        pipeline = build_preprocessing_pipeline()
        assert pipeline is not None
        assert len(pipeline.steps) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
