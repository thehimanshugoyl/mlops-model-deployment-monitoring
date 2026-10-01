"""
Drift Detection Engine.
Calculates statistical drift between baseline reference data and incoming production data
using Kolmogorov-Smirnov (KS) test, Population Stability Index (PSI), and Wasserstein Distance.
"""

from collections import deque
import logging
import threading
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp, wasserstein_distance

logger = logging.getLogger(__name__)


def calculate_psi(
    reference: np.ndarray, current: np.ndarray, num_bins: int = 10, epsilon: float = 1e-4
) -> float:
    """
    Calculate the Population Stability Index (PSI) between reference and current samples.
    PSI < 0.1: No significant change
    0.1 <= PSI < 0.2: Moderate drift
    PSI >= 0.2: Significant drift
    """
    reference = np.asarray(reference, dtype=float)
    current = np.asarray(current, dtype=float)

    # Remove any NaN or infinite values
    reference = reference[np.isfinite(reference)]
    current = current[np.isfinite(current)]

    if len(reference) == 0 or len(current) == 0:
        return 0.0

    # Quantile bin edges based on reference distribution
    quantiles = np.linspace(0, 100, num_bins + 1)
    bin_edges = np.percentile(reference, quantiles)
    bin_edges[0] = -np.inf
    bin_edges[-1] = np.inf

    # Ensure strictly increasing bins
    for i in range(1, len(bin_edges)):
        if bin_edges[i] <= bin_edges[i - 1]:
            bin_edges[i] = bin_edges[i - 1] + 1e-5

    ref_counts, _ = np.histogram(reference, bins=bin_edges)
    curr_counts, _ = np.histogram(current, bins=bin_edges)

    ref_pct = np.maximum(ref_counts / len(reference), epsilon)
    curr_pct = np.maximum(curr_counts / len(current), epsilon)

    psi_value = np.sum((curr_pct - ref_pct) * np.log(curr_pct / ref_pct))
    return float(np.round(psi_value, 4))


class DriftDetector:
    """
    Monitors streaming production inputs and computes feature-level & dataset-level drift
    against a reference baseline dataset.
    """

    def __init__(
        self,
        reference_df: pd.DataFrame,
        feature_names: List[str],
        window_size: int = 500,
        min_samples_to_evaluate: int = 25,
        p_value_threshold: float = 0.05,
        drift_share_threshold: float = 0.30,
    ):
        self.feature_names = feature_names
        self.reference_df = reference_df[feature_names].copy()
        self.window_size = window_size
        self.min_samples_to_evaluate = min_samples_to_evaluate
        self.p_value_threshold = p_value_threshold
        self.drift_share_threshold = drift_share_threshold

        self._buffer: deque = deque(maxlen=window_size)
        self._lock = threading.Lock()

    def record_prediction_features(self, features: Dict[str, Any]) -> None:
        """
        Record a single incoming production observation into the sliding buffer.
        """
        row = {col: features.get(col, np.nan) for col in self.feature_names}
        with self._lock:
            self._buffer.append(row)

    def record_batch_features(self, features_list: List[Dict[str, Any]]) -> None:
        """
        Record multiple incoming production observations.
        """
        with self._lock:
            for feat in features_list:
                row = {col: feat.get(col, np.nan) for col in self.feature_names}
                self._buffer.append(row)

    def get_buffer_size(self) -> int:
        with self._lock:
            return len(self._buffer)

    def reset_buffer(self) -> None:
        with self._lock:
            self._buffer.clear()

    def evaluate_drift(self) -> Dict[str, Any]:
        """
        Runs statistical tests (KS test, PSI, Wasserstein) for each feature.
        Returns detailed drift report.
        """
        with self._lock:
            current_samples = list(self._buffer)

        if len(current_samples) < self.min_samples_to_evaluate:
            return {
                "status": "insufficient_data",
                "sample_count": len(current_samples),
                "min_samples_required": self.min_samples_to_evaluate,
                "dataset_drift_detected": False,
                "drift_share": 0.0,
                "drifted_features_count": 0,
                "total_features": len(self.feature_names),
                "features": {},
            }

        curr_df = pd.DataFrame(current_samples)
        feature_results: Dict[str, Any] = {}
        drifted_count = 0

        for feature in self.feature_names:
            ref_vals = self.reference_df[feature].to_numpy(dtype=float)
            curr_vals = curr_df[feature].to_numpy(dtype=float)

            # Kolmogorov-Smirnov Test
            ks_res = ks_2samp(ref_vals, curr_vals)
            ks_stat = float(np.round(ks_res.statistic, 4))
            p_val = float(np.round(ks_res.pvalue, 6))

            # Population Stability Index (PSI)
            psi_val = calculate_psi(ref_vals, curr_vals)

            # Wasserstein Distance
            # Normalize by ref standard deviation to make distance scale-invariant
            ref_std = np.std(ref_vals)
            std_norm = ref_std if ref_std > 1e-6 else 1.0
            w_dist = float(np.round(wasserstein_distance(ref_vals, curr_vals) / std_norm, 4))

            # Drift is flagged if KS p-value is below threshold or PSI >= 0.2
            is_drifted = (p_val < self.p_value_threshold) or (psi_val >= 0.2)
            if is_drifted:
                drifted_count += 1

            feature_results[feature] = {
                "drift_detected": bool(is_drifted),
                "ks_statistic": ks_stat,
                "p_value": p_val,
                "psi": psi_val,
                "wasserstein_distance": w_dist,
                "ref_mean": float(np.round(np.mean(ref_vals), 2)),
                "curr_mean": float(np.round(np.mean(curr_vals), 2)),
                "ref_std": float(np.round(np.std(ref_vals), 2)),
                "curr_std": float(np.round(np.std(curr_vals), 2)),
            }

        drift_share = float(np.round(drifted_count / len(self.feature_names), 4))
        dataset_drift = drift_share >= self.drift_share_threshold

        return {
            "status": "evaluated",
            "sample_count": len(current_samples),
            "min_samples_required": self.min_samples_to_evaluate,
            "dataset_drift_detected": bool(dataset_drift),
            "drift_share": drift_share,
            "drifted_features_count": drifted_count,
            "total_features": len(self.feature_names),
            "features": feature_results,
        }
