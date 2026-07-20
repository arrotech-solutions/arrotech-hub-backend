"""
A/B testing service for Mini-Hub MCP Server.
"""

import logging
import math
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class ABTestingService:
    """A/B testing and experimentation service."""

    def __init__(self):
        self.tests = {}  # In-memory storage for tests
        self.results = {}  # In-memory storage for test results
        self.variants = {}  # In-memory storage for test variants

    async def create_test(
        self,
        test_name: str,
        test_type: str,
        variants: List[Dict[str, Any]],
        traffic_split: Dict[str, float],
        primary_metric: str,
        secondary_metrics: List[str],
        duration_days: int = 14
    ) -> Dict[str, Any]:
        """Create a new A/B test."""
        try:
            test_id = str(uuid4())

            # Validate traffic split
            total_split = sum(traffic_split.values())
            if abs(total_split - 1.0) > 0.01:
                return {
                    "success": False,
                    "error": "Traffic split must sum to 1.0"
                }

            test = {
                "id": test_id,
                "name": test_name,
                "type": test_type,
                "variants": variants,
                "traffic_split": traffic_split,
                "primary_metric": primary_metric,
                "secondary_metrics": secondary_metrics,
                "duration_days": duration_days,
                "status": "draft",
                "created_at": datetime.now().isoformat(),
                "start_date": None,
                "end_date": None,
                "results": {}
            }

            self.tests[test_id] = test

            # Store variants
            for variant in variants:
                variant_id = variant.get("id", str(uuid4()))
                self.variants[variant_id] = {
                    **variant,
                    "test_id": test_id
                }

            logger.info(f"Created A/B test {test_id}: {test_name}")

            return {
                "success": True,
                "test_id": test_id,
                "test": test
            }

        except Exception as e:
            logger.error(f"Error creating A/B test: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def start_test(self, test_id: str) -> Dict[str, Any]:
        """Start an A/B test."""
        try:
            if test_id not in self.tests:
                return {
                    "success": False,
                    "error": f"Test {test_id} not found"
                }

            test = self.tests[test_id]
            if test["status"] != "draft":
                return {
                    "success": False,
                    "error": f"Test {test_id} is not in draft status"
                }

            # Update test status
            test["status"] = "running"
            test["start_date"] = datetime.now().isoformat()
            test["end_date"] = (
                datetime.now() + timedelta(days=test["duration_days"])
            ).isoformat()

            return {
                "success": True,
                "test_id": test_id,
                "message": f"Test {test['name']} started successfully"
            }

        except Exception as e:
            logger.error(f"Error starting A/B test: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def record_conversion(
        self,
        test_id: str,
        variant_id: str,
        user_id: str,
        metrics: Dict[str, float]
    ) -> Dict[str, Any]:
        """Record a conversion for a test variant."""
        try:
            if test_id not in self.tests:
                return {
                    "success": False,
                    "error": f"Test {test_id} not found"
                }

            test = self.tests[test_id]
            if test["status"] != "running":
                return {
                    "success": False,
                    "error": f"Test {test_id} is not running"
                }

            # Initialize results if not exists
            if test_id not in self.results:
                self.results[test_id] = {}

            if variant_id not in self.results[test_id]:
                self.results[test_id][variant_id] = {
                    "conversions": 0,
                    "visitors": 0,
                    "metrics": {},
                    "conversion_rate": 0.0
                }

            # Update results
            result = self.results[test_id][variant_id]
            result["conversions"] += 1
            result["visitors"] += 1

            # Update metrics
            for metric_name, value in metrics.items():
                if metric_name not in result["metrics"]:
                    result["metrics"][metric_name] = 0
                result["metrics"][metric_name] += value

            # Calculate conversion rate
            result["conversion_rate"] = (
                result["conversions"] / result["visitors"] * 100
            )

            return {
                "success": True,
                "test_id": test_id,
                "variant_id": variant_id,
                "conversion_recorded": True
            }

        except Exception as e:
            logger.error(f"Error recording conversion: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_test_results(self, test_id: str) -> Dict[str, Any]:
        """Get results for an A/B test."""
        try:
            if test_id not in self.tests:
                return {
                    "success": False,
                    "error": f"Test {test_id} not found"
                }

            test = self.tests[test_id]
            results = self.results.get(test_id, {})

            # Calculate statistical significance
            significance_results = self._calculate_statistical_significance(
                test, results
            )

            # Determine winner
            winner = self._determine_winner(
                test, results, significance_results)

            return {
                "success": True,
                "test_id": test_id,
                "test": test,
                "results": results,
                "significance": significance_results,
                "winner": winner,
                "recommendations": self._generate_test_recommendations(
                    test, results, significance_results
                )
            }

        except Exception as e:
            logger.error(f"Error getting test results: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _calculate_statistical_significance(
        self,
        test: Dict[str, Any],
        results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Calculate statistical significance between variants."""
        if len(results) < 2:
            return {"significant": False, "confidence": 0.0}

        # Get control and treatment variants
        variants = list(results.keys())
        control_variant = variants[0]
        treatment_variant = variants[1]

        control_data = results[control_variant]
        treatment_data = results[treatment_variant]

        # Calculate conversion rates
        control_rate = control_data["conversion_rate"] / 100
        treatment_rate = treatment_data["conversion_rate"] / 100

        # Calculate sample sizes
        n1 = control_data["visitors"]
        n2 = treatment_data["visitors"]

        if n1 == 0 or n2 == 0:
            return {"significant": False, "confidence": 0.0}

        # Calculate pooled standard error
        pooled_p = (control_rate * n1 + treatment_rate * n2) / (n1 + n2)
        pooled_se = math.sqrt(
            pooled_p * (1 - pooled_p) * (1/n1 + 1/n2)
        )

        if pooled_se == 0:
            return {"significant": False, "confidence": 0.0}

        # Calculate z-score
        z_score = (treatment_rate - control_rate) / pooled_se

        # Calculate p-value (simplified)
        p_value = 2 * (1 - self._normal_cdf(abs(z_score)))

        # Calculate confidence level
        confidence = (1 - p_value) * 100

        return {
            "significant": p_value < 0.05,
            "confidence": round(confidence, 2),
            "p_value": round(p_value, 4),
            "z_score": round(z_score, 3),
            "lift": round((treatment_rate - control_rate) / control_rate * 100, 2)
        }

    def _normal_cdf(self, x: float) -> float:
        """Approximate normal cumulative distribution function."""
        # Simplified approximation
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    def _determine_winner(
        self,
        test: Dict[str, Any],
        results: Dict[str, Any],
        significance: Dict[str, Any]
    ) -> Optional[str]:
        """Determine the winning variant."""
        if not significance["significant"]:
            return None

        # Find variant with highest conversion rate
        best_variant = None
        best_rate = 0.0

        for variant_id, result in results.items():
            if result["conversion_rate"] > best_rate:
                best_rate = result["conversion_rate"]
                best_variant = variant_id

        return best_variant

    def _generate_test_recommendations(
        self,
        test: Dict[str, Any],
        results: Dict[str, Any],
        significance: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate recommendations based on test results."""
        recommendations = []

        if significance["significant"]:
            recommendations.append({
                "type": "implementation",
                "priority": "high",
                "title": "Implement winning variant",
                "description": f"Test shows {significance['lift']}% lift with {significance['confidence']}% confidence",
                "actions": [
                    "Deploy winning variant to 100% traffic",
                    "Monitor post-launch performance",
                    "Document learnings"
                ]
            })
        else:
            recommendations.append({
                "type": "optimization",
                "priority": "medium",
                "title": "Test not statistically significant",
                "description": "Continue test or try different variations",
                "actions": [
                    "Extend test duration",
                    "Increase sample size",
                    "Try different variations"
                ]
            })

        return recommendations

    async def stop_test(self, test_id: str) -> Dict[str, Any]:
        """Stop an A/B test."""
        try:
            if test_id not in self.tests:
                return {
                    "success": False,
                    "error": f"Test {test_id} not found"
                }

            test = self.tests[test_id]
            if test["status"] != "running":
                return {
                    "success": False,
                    "error": f"Test {test_id} is not running"
                }

            # Update test status
            test["status"] = "stopped"
            test["end_date"] = datetime.now().isoformat()

            return {
                "success": True,
                "test_id": test_id,
                "message": f"Test {test['name']} stopped successfully"
            }

        except Exception as e:
            logger.error(f"Error stopping A/B test: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_test_analytics(
        self,
        test_id: Optional[str] = None,
        date_range: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get analytics for A/B tests."""
        try:
            # Filter tests
            filtered_tests = []
            for test in self.tests.values():
                if test_id and test["id"] != test_id:
                    continue
                filtered_tests.append(test)

            # Calculate analytics
            total_tests = len(filtered_tests)
            running_tests = len(
                [t for t in filtered_tests if t["status"] == "running"])
            completed_tests = len(
                [t for t in filtered_tests if t["status"] == "stopped"])

            # Calculate success rate
            successful_tests = 0
            for test in filtered_tests:
                if test["status"] == "stopped":
                    results = self.results.get(test["id"], {})
                    if results:
                        significance = self._calculate_statistical_significance(
                            test, results
                        )
                        if significance["significant"]:
                            successful_tests += 1

            success_rate = (
                successful_tests / completed_tests * 100 if completed_tests > 0 else 0
            )

            analytics = {
                "total_tests": total_tests,
                "running_tests": running_tests,
                "completed_tests": completed_tests,
                "success_rate": round(success_rate, 2),
                "recent_tests": filtered_tests[-5:] if filtered_tests else []
            }

            return {
                "success": True,
                "analytics": analytics
            }

        except Exception as e:
            logger.error(f"Error getting test analytics: {e}")
            return {
                "success": False,
                "error": str(e)
            }
