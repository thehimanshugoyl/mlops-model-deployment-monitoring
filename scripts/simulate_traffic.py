"""
Traffic Simulator and Drift Injection Generator.
Simulates realistic production requests against the ML model service,
demonstrating both normal traffic and intentional statistical data drift.
"""

import argparse
import logging
import random
import sys
import time
from typing import Dict, Any

import requests

# Enable immediate stdout flushing
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("traffic_simulator")

# Persistent HTTP session with keep-alive
session = requests.Session()


def send_prediction(
    host: str, sample: Dict[str, Any], max_retries: int = 3
) -> Dict[str, Any]:
    global session
    url = f"{host.rstrip('/')}/predict"
    for attempt in range(max_retries):
        try:
            resp = session.post(url, json=sample, timeout=5.0)
            resp.raise_for_status()
            return resp.json()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt == max_retries - 1:
                raise e
            session = requests.Session()
            time.sleep(0.2)


def check_drift_status(host: str, max_retries: int = 3) -> Dict[str, Any]:
    global session
    url = f"{host.rstrip('/')}/drift"
    for attempt in range(max_retries):
        try:
            resp = session.get(url, timeout=5.0)
            resp.raise_for_status()
            return resp.json()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt == max_retries - 1:
                raise e
            session = requests.Session()
            time.sleep(0.2)


def generate_normal_sample() -> Dict[str, Any]:
    """Generates an applicant matching the baseline training distribution."""
    age = int(random.gauss(42, 10))
    age = max(21, min(65, age))

    annual_income = round(max(20000.0, random.gauss(65000, 22000)), 2)
    credit_score = int(max(350, min(850, random.gauss(680, 75))))
    loan_amount = round(max(2000.0, random.gauss(20000, 9000)), 2)
    loan_tenure = random.choice([12, 24, 36, 48, 60])
    debt_to_income = round(max(0.05, min(0.75, random.betavariate(2, 5) * 0.7)), 4)
    employment_years = round(min(35.0, random.expovariate(1 / 5.0)), 1)
    has_prior_default = 1 if random.random() < 0.12 else 0

    return {
        "age": age,
        "annual_income": annual_income,
        "credit_score": credit_score,
        "loan_amount": loan_amount,
        "loan_tenure_months": loan_tenure,
        "debt_to_income_ratio": debt_to_income,
        "employment_years": employment_years,
        "has_prior_default": has_prior_default,
    }


def generate_drifted_sample() -> Dict[str, Any]:
    """
    Generates an applicant from an intentionally shifted distribution (simulating economic distress / regime shift):
    - Substantially lower credit scores (mean 510 vs 680)
    - Dramatically higher debt-to-income ratios (mean 0.65 vs 0.28)
    - Shorter employment durations (mean 1.5 vs 5.0)
    - Much higher prior default rates (45% vs 12%)
    """
    age = int(random.gauss(28, 6))  # Younger demographic shift
    age = max(19, min(50, age))

    annual_income = round(max(15000.0, random.gauss(38000, 14000)), 2)  # Income drop
    credit_score = int(max(300, min(680, random.gauss(520, 60))))  # Credit degradation
    loan_amount = round(max(5000.0, random.gauss(32000, 12000)), 2)  # Higher borrowing
    loan_tenure = random.choice([36, 48, 60])
    debt_to_income = round(
        max(0.40, min(1.20, random.gauss(0.65, 0.15))), 4
    )  # High leverage
    employment_years = round(min(10.0, random.expovariate(1 / 1.5)), 1)
    has_prior_default = 1 if random.random() < 0.45 else 0

    return {
        "age": age,
        "annual_income": annual_income,
        "credit_score": credit_score,
        "loan_amount": loan_amount,
        "loan_tenure_months": loan_tenure,
        "debt_to_income_ratio": debt_to_income,
        "employment_years": employment_years,
        "has_prior_default": has_prior_default,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Simulate Traffic & Drift for ML Service"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="http://localhost:8000",
        help="Base URL of ML service",
    )
    parser.add_argument(
        "--mode",
        choices=["normal", "drifted", "scenario", "continuous"],
        default="scenario",
        help="Traffic mode to run",
    )
    parser.add_argument(
        "--requests", type=int, default=60, help="Number of requests per phase"
    )
    parser.add_argument(
        "--delay", type=float, default=0.05, help="Delay between requests in seconds"
    )
    args = parser.parse_args()

    logger.info("Connecting to model service at %s", args.host)
    try:
        health_resp = requests.get(f"{args.host}/health", timeout=3.0)
        logger.info("Service Health Check: %s", health_resp.json().get("status"))
    except Exception as e:
        logger.error("Failed to connect to %s: %s", args.host, e)
        sys.exit(1)

    if args.mode == "normal":
        logger.info("Sending %d NORMAL requests...", args.requests)
        for i in range(args.requests):
            sample = generate_normal_sample()
            res = send_prediction(args.host, sample)
            pred = res["results"][0]
            logger.info(
                "[%d/%d] Normal -> Pred: %d, Prob: %.3f, Risk: %s, Latency: %.1fms",
                i + 1,
                args.requests,
                pred["prediction"],
                pred["default_probability"],
                pred["risk_level"],
                res["latency_ms"],
            )
            time.sleep(args.delay)

    elif args.mode == "drifted":
        logger.info("Sending %d DRIFTED requests...", args.requests)
        for i in range(args.requests):
            sample = generate_drifted_sample()
            res = send_prediction(args.host, sample)
            pred = res["results"][0]
            logger.info(
                "[%d/%d] Drifted -> Pred: %d, Prob: %.3f, Risk: %s, Latency: %.1fms",
                i + 1,
                args.requests,
                pred["prediction"],
                pred["default_probability"],
                pred["risk_level"],
                res["latency_ms"],
            )
            time.sleep(args.delay)

    elif args.mode == "scenario":
        logger.info("=== SCENARIO MODE: Phase 1 (Baseline Traffic - 40 requests) ===")
        # Reset buffer for clean baseline test
        requests.post(f"{args.host}/drift/reset")
        for i in range(40):
            sample = generate_normal_sample()
            res = send_prediction(args.host, sample)
            time.sleep(args.delay)

        baseline_drift = check_drift_status(args.host)
        logger.info(
            "Phase 1 Baseline Drift Result: Detected=%s (Drift share: %.1f%%, Drifted features: %d)",
            baseline_drift.get("dataset_drift_detected"),
            baseline_drift.get("drift_share", 0.0) * 100,
            baseline_drift.get("drifted_features_count", 0),
        )

        logger.info(
            "=== SCENARIO MODE: Phase 2 (Injecting Statistical Drift - 45 requests) ==="
        )
        for i in range(45):
            sample = generate_drifted_sample()
            res = send_prediction(args.host, sample)
            time.sleep(args.delay)

        drifted_report = check_drift_status(args.host)
        logger.info(
            "Phase 2 Drift Result: Detected=%s (Drift share: %.1f%%, Drifted features: %d)",
            drifted_report.get("dataset_drift_detected"),
            drifted_report.get("drift_share", 0.0) * 100,
            drifted_report.get("drifted_features_count", 0),
        )

        logger.info("--- Feature Breakdown ---")
        for feat, data in drifted_report.get("features", {}).items():
            status_str = "DRIFT DETECTED" if data["drift_detected"] else "STABLE"
            logger.info(
                "  %-22s : %-15s (KS p-val: %.4f, PSI: %.3f, Ref Mean: %.2f -> Curr Mean: %.2f)",
                feat,
                status_str,
                data["p_value"],
                data["psi"],
                data["ref_mean"],
                data["curr_mean"],
            )

    elif args.mode == "continuous":
        logger.info("Starting continuous simulation loop (Ctrl+C to terminate)...")
        iteration = 0
        while True:
            iteration += 1
            is_drift = iteration % 4 == 0  # Drift every 4th batch
            generator = generate_drifted_sample if is_drift else generate_normal_sample
            tag = "DRIFTED" if is_drift else "NORMAL"
            logger.info("Iteration %d: Sending 10 %s requests...", iteration, tag)
            for _ in range(10):
                sample = generator()
                send_prediction(args.host, sample)
                time.sleep(args.delay)

            drift_info = check_drift_status(args.host)
            logger.info(
                "Status: Dataset Drift = %s, Drifted Features = %d/%d",
                drift_info.get("dataset_drift_detected"),
                drift_info.get("drifted_features_count", 0),
                drift_info.get("total_features", 0),
            )
            time.sleep(1.0)


if __name__ == "__main__":
    main()
