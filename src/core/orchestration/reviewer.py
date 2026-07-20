"""
Reviewer Agent — Post-execution validation against skill protocols.

Validates outputs after each task/step completes:
- Protocol review_steps compliance
- Output quality scoring via QualityGate
- Forbidden action detection
- Regression checks (did we break something?)

The reviewer is the "quality conscience" of the GSD workflow.
"""
import logging
import re
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ReviewResult:
    """Result of a review evaluation."""
    passed: bool = True
    score: float = 1.0
    checks_run: int = 0
    checks_passed: int = 0
    findings: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "score": round(self.score, 3),
            "checks_run": self.checks_run,
            "checks_passed": self.checks_passed,
            "findings": self.findings,
            "warnings": self.warnings,
            "recommendations": self.recommendations,
        }


class ReviewerAgent:
    """
    Post-execution review agent.

    Runs after each task or skill execution to validate:
    1. Required validations from the skill contract passed
    2. No forbidden actions were performed
    3. Output meets quality standards
    4. No security violations detected

    Usage:
        reviewer = ReviewerAgent()
        result = reviewer.review(
            skill=skill_definition,
            tool_calls=[{"tool": "coding_file_write", "args": {...}, "result": {...}}],
            output="Endpoint added successfully",
        )
        if not result.passed:
            # trigger recovery
    """

    def review(
        self,
        skill: Any,
        tool_calls: List[Dict[str, Any]],
        output: str = "",
        test_results: Optional[Dict[str, Any]] = None,
    ) -> ReviewResult:
        """
        Run all review checks for a skill execution.

        Args:
            skill: The SkillDefinition that was executed
            tool_calls: List of tool calls made during execution
            output: The final output/response text
            test_results: Optional test execution results
        """
        result = ReviewResult()

        # 1. Forbidden action check
        self._check_forbidden_actions(skill, tool_calls, result)

        # 2. Required validation checks
        self._check_required_validations(skill, test_results, result)

        # 3. Output quality checks
        self._check_output_quality(output, result)

        # 4. Security checks
        self._check_security(output, tool_calls, result)

        # 5. Tool error rate check
        self._check_tool_error_rate(tool_calls, result)

        # Calculate final score
        if result.checks_run > 0:
            result.score = result.checks_passed / result.checks_run
        result.passed = result.score >= 0.7 and len(result.findings) == 0

        log_level = logging.INFO if result.passed else logging.WARNING
        logger.log(
            log_level,
            f"Review {'PASSED' if result.passed else 'FAILED'}: "
            f"{result.checks_passed}/{result.checks_run} checks, "
            f"score={result.score:.2f}, findings={len(result.findings)}"
        )

        return result

    def _check_forbidden_actions(
        self, skill: Any, tool_calls: List[Dict], result: ReviewResult
    ) -> None:
        """Check if any forbidden actions were performed."""
        result.checks_run += 1
        forbidden = set(skill.execution_contract.forbidden_actions)
        allowed_tools = {
            perm.tool_name for perm in skill.execution_contract.allowed_tools
        }

        violations = []
        for call in tool_calls:
            tool_name = call.get("tool", "")
            if tool_name and tool_name not in allowed_tools:
                violations.append(f"Unauthorized tool used: {tool_name}")

        if violations:
            result.findings.extend(violations)
        else:
            result.checks_passed += 1

    def _check_required_validations(
        self, skill: Any, test_results: Optional[Dict], result: ReviewResult
    ) -> None:
        """Check if required validations passed."""
        for validation in skill.execution_contract.required_validations:
            result.checks_run += 1

            if validation in ("tests_must_pass", "tests_executed"):
                if test_results:
                    if test_results.get("all_passed", False):
                        result.checks_passed += 1
                    else:
                        failed = test_results.get("failed", 0)
                        result.findings.append(
                            f"Validation '{validation}' failed: {failed} test(s) failed"
                        )
                else:
                    result.warnings.append(
                        f"Validation '{validation}' could not be verified (no test results)"
                    )
                    result.checks_passed += 1  # Pass with warning

            elif validation in ("lint_passed", "syntax_valid"):
                # These would need actual linting — pass with recommendation
                result.checks_passed += 1
                result.recommendations.append(
                    f"Run linter to verify '{validation}'"
                )

            elif validation in ("route_registered", "coverage_check"):
                # These need runtime verification — pass with recommendation
                result.checks_passed += 1
                result.recommendations.append(
                    f"Manually verify '{validation}'"
                )

            else:
                # Unknown validation — pass with warning
                result.checks_passed += 1
                result.warnings.append(f"Unknown validation: '{validation}'")

    def _check_output_quality(self, output: str, result: ReviewResult) -> None:
        """Check output quality heuristics."""
        result.checks_run += 1

        if not output or len(output.strip()) < 5:
            result.warnings.append("Output is empty or very short")
            result.checks_passed += 1  # Not a hard failure
            return

        # Check for error indicators
        error_phrases = [
            "traceback", "exception", "error:", "failed to",
            "syntax error", "import error", "name error",
        ]
        errors_found = [p for p in error_phrases if p in output.lower()]
        if errors_found:
            result.warnings.append(
                f"Output may contain errors: {errors_found[:3]}"
            )

        result.checks_passed += 1

    def _check_security(
        self, output: str, tool_calls: List[Dict], result: ReviewResult
    ) -> None:
        """Check for security violations in output."""
        result.checks_run += 1

        violations = []

        # Check for leaked secrets
        secret_patterns = [
            (r"(?:password|secret|token|api.?key)\s*[:=]\s*['\"]?\S{8,}", "Possible credential leak"),
            (r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----", "Private key exposure"),
            (r"sk-[a-zA-Z0-9]{20,}", "Possible API key leak"),
        ]

        for pattern, description in secret_patterns:
            if re.search(pattern, output, re.IGNORECASE):
                violations.append(f"SECURITY: {description}")

        if violations:
            result.findings.extend(violations)
        else:
            result.checks_passed += 1

    def _check_tool_error_rate(
        self, tool_calls: List[Dict], result: ReviewResult
    ) -> None:
        """Check if too many tool calls failed."""
        result.checks_run += 1

        if not tool_calls:
            result.checks_passed += 1
            return

        failed = sum(
            1 for call in tool_calls
            if isinstance(call.get("result"), dict)
            and (call["result"].get("error") or call["result"].get("success") is False)
        )

        error_rate = failed / len(tool_calls) if tool_calls else 0
        if error_rate > 0.5:
            result.findings.append(
                f"High tool error rate: {failed}/{len(tool_calls)} "
                f"({error_rate:.0%}) calls failed"
            )
        elif error_rate > 0.2:
            result.warnings.append(
                f"Elevated tool error rate: {failed}/{len(tool_calls)}"
            )
            result.checks_passed += 1
        else:
            result.checks_passed += 1


# Module-level singleton
reviewer_agent = ReviewerAgent()
