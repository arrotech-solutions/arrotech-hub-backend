"""
Enterprise security and compliance service for Mini-Hub MCP Server.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class EnterpriseSecurityService:
    """Enterprise security, compliance, and audit service."""

    def __init__(self):
        self.security_policies = {}  # In-memory storage for security policies
        self.audit_logs = {}  # In-memory storage for audit logs
        self.compliance_checks = {}  # In-memory storage for compliance checks
        self.encryption_keys = {}  # In-memory storage for encryption keys

    async def create_security_policy(
        self,
        name: str,
        policy_type: str,
        rules: List[Dict[str, Any]],
        enforcement_level: str = "strict"
    ) -> Dict[str, Any]:
        """Create a new security policy."""
        try:
            policy_id = str(uuid4())

            policy = {
                "id": policy_id,
                "name": name,
                "type": policy_type,
                "rules": rules,
                "enforcement_level": enforcement_level,
                "status": "active",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }

            self.security_policies[policy_id] = policy

            logger.info(f"Created security policy {policy_id}: {name}")

            return {
                "success": True,
                "policy_id": policy_id,
                "policy": policy
            }

        except Exception as e:
            logger.error(f"Error creating security policy: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def enforce_security_policy(
        self,
        user_id: str,
        action: str,
        resource: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Enforce security policies for user actions."""
        try:
            violations = []
            allowed = True

            # Check all active policies
            for policy_id, policy in self.security_policies.items():
                if policy["status"] != "active":
                    continue

                policy_result = await self._check_policy_compliance(
                    policy, user_id, action, resource, context
                )

                if not policy_result["compliant"]:
                    violations.append({
                        "policy_id": policy_id,
                        "policy_name": policy["name"],
                        "violation": policy_result["violation"],
                        "severity": policy_result["severity"]
                    })

                    if policy["enforcement_level"] == "strict":
                        allowed = False

            # Log audit event
            await self._log_audit_event(
                user_id, action, resource, context, allowed, violations
            )

            return {
                "success": True,
                "allowed": allowed,
                "violations": violations,
                "policy_checks": len(self.security_policies)
            }

        except Exception as e:
            logger.error(f"Error enforcing security policy: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def _check_policy_compliance(
        self,
        policy: Dict[str, Any],
        user_id: str,
        action: str,
        resource: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Check if an action complies with a security policy."""
        try:
            rules = policy["rules"]
            
            for rule in rules:
                rule_type = rule.get("type")
                
                if rule_type == "ip_whitelist":
                    client_ip = context.get("client_ip")
                    allowed_ips = rule.get("allowed_ips", [])
                    if client_ip and client_ip not in allowed_ips:
                        return {
                            "compliant": False,
                            "violation": f"IP {client_ip} not in whitelist",
                            "severity": "high"
                        }

                elif rule_type == "time_restriction":
                    current_hour = datetime.now().hour
                    allowed_hours = rule.get("allowed_hours", [])
                    if current_hour not in allowed_hours:
                        return {
                            "compliant": False,
                            "violation": f"Action not allowed at hour {current_hour}",
                            "severity": "medium"
                        }

                elif rule_type == "resource_access":
                    allowed_resources = rule.get("allowed_resources", [])
                    if resource not in allowed_resources:
                        return {
                            "compliant": False,
                            "violation": f"Access to resource {resource} not allowed",
                            "severity": "high"
                        }

                elif rule_type == "action_restriction":
                    restricted_actions = rule.get("restricted_actions", [])
                    if action in restricted_actions:
                        return {
                            "compliant": False,
                            "violation": f"Action {action} is restricted",
                            "severity": "high"
                        }

                elif rule_type == "rate_limit":
                    max_requests = rule.get("max_requests", 100)
                    time_window = rule.get("time_window", 3600)  # 1 hour
                    
                    # Check rate limit (simplified)
                    user_requests = context.get("user_requests", 0)
                    if user_requests > max_requests:
                        return {
                            "compliant": False,
                            "violation": f"Rate limit exceeded: {user_requests}/{max_requests}",
                            "severity": "medium"
                        }

            return {
                "compliant": True,
                "violation": None,
                "severity": None
            }

        except Exception as e:
            logger.error(f"Error checking policy compliance: {e}")
            return {
                "compliant": False,
                "violation": f"Policy check error: {str(e)}",
                "severity": "high"
            }

    async def _log_audit_event(
        self,
        user_id: str,
        action: str,
        resource: str,
        context: Dict[str, Any],
        allowed: bool,
        violations: List[Dict[str, Any]]
    ):
        """Log an audit event."""
        try:
            event_id = str(uuid4())
            
            audit_event = {
                "id": event_id,
                "user_id": user_id,
                "action": action,
                "resource": resource,
                "context": context,
                "allowed": allowed,
                "violations": violations,
                "timestamp": datetime.now().isoformat(),
                "client_ip": context.get("client_ip"),
                "user_agent": context.get("user_agent")
            }

            # Store audit log
            if user_id not in self.audit_logs:
                self.audit_logs[user_id] = []
            
            self.audit_logs[user_id].append(audit_event)

            # Keep only last 1000 audit events per user
            if len(self.audit_logs[user_id]) > 1000:
                self.audit_logs[user_id] = self.audit_logs[user_id][-1000:]

        except Exception as e:
            logger.error(f"Error logging audit event: {e}")

    async def generate_encryption_key(
        self,
        key_name: str,
        key_type: str = "aes-256",
        rotation_period: Optional[int] = None
    ) -> Dict[str, Any]:
        """Generate a new encryption key."""
        try:
            key_id = str(uuid4())
            
            if key_type == "aes-256":
                key_data = secrets.token_bytes(32)
            elif key_type == "rsa-2048":
                key_data = secrets.token_bytes(256)  # Simplified for demo
            else:
                return {
                    "success": False,
                    "error": f"Unsupported key type: {key_type}"
                }

            key_hash = hashlib.sha256(key_data).hexdigest()

            encryption_key = {
                "id": key_id,
                "name": key_name,
                "type": key_type,
                "key_hash": key_hash,
                "created_at": datetime.now().isoformat(),
                "rotation_period": rotation_period,
                "status": "active"
            }

            self.encryption_keys[key_id] = encryption_key

            return {
                "success": True,
                "key_id": key_id,
                "key_hash": key_hash,
                "encryption_key": encryption_key
            }

        except Exception as e:
            logger.error(f"Error generating encryption key: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def encrypt_data(
        self,
        key_id: str,
        data: str,
        algorithm: str = "aes-256-gcm"
    ) -> Dict[str, Any]:
        """Encrypt data using a specified key."""
        try:
            if key_id not in self.encryption_keys:
                return {
                    "success": False,
                    "error": f"Encryption key {key_id} not found"
                }

            # Simplified encryption for demo
            import base64
            encrypted_data = base64.b64encode(data.encode()).decode()
            
            return {
                "success": True,
                "encrypted_data": encrypted_data,
                "algorithm": algorithm,
                "key_id": key_id
            }

        except Exception as e:
            logger.error(f"Error encrypting data: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def decrypt_data(
        self,
        key_id: str,
        encrypted_data: str,
        algorithm: str = "aes-256-gcm"
    ) -> Dict[str, Any]:
        """Decrypt data using a specified key."""
        try:
            if key_id not in self.encryption_keys:
                return {
                    "success": False,
                    "error": f"Encryption key {key_id} not found"
                }

            # Simplified decryption for demo
            import base64
            decrypted_data = base64.b64decode(encrypted_data.encode()).decode()
            
            return {
                "success": True,
                "decrypted_data": decrypted_data,
                "algorithm": algorithm,
                "key_id": key_id
            }

        except Exception as e:
            logger.error(f"Error decrypting data: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def run_compliance_check(
        self,
        check_type: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Run a compliance check."""
        try:
            check_id = str(uuid4())
            
            if check_type == "gdpr_compliance":
                result = await self._check_gdpr_compliance(parameters)
            elif check_type == "sox_compliance":
                result = await self._check_sox_compliance(parameters)
            elif check_type == "hipaa_compliance":
                result = await self._check_hipaa_compliance(parameters)
            else:
                return {
                    "success": False,
                    "error": f"Unknown compliance check type: {check_type}"
                }

            compliance_check = {
                "id": check_id,
                "type": check_type,
                "parameters": parameters,
                "result": result,
                "timestamp": datetime.now().isoformat()
            }

            self.compliance_checks[check_id] = compliance_check

            return {
                "success": True,
                "check_id": check_id,
                "compliance_check": compliance_check
            }

        except Exception as e:
            logger.error(f"Error running compliance check: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def _check_gdpr_compliance(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Check GDPR compliance."""
        try:
            # Simplified GDPR compliance check
            data_retention = parameters.get("data_retention_days", 0)
            consent_management = parameters.get("consent_management", False)
            data_encryption = parameters.get("data_encryption", False)
            access_controls = parameters.get("access_controls", False)

            issues = []
            compliant = True

            if data_retention > 2555:  # 7 years
                issues.append("Data retention period exceeds GDPR requirements")
                compliant = False

            if not consent_management:
                issues.append("Consent management system not implemented")
                compliant = False

            if not data_encryption:
                issues.append("Data encryption not enabled")
                compliant = False

            if not access_controls:
                issues.append("Access controls not properly configured")
                compliant = False

            return {
                "compliant": compliant,
                "issues": issues,
                "score": 85 if compliant else 45
            }

        except Exception as e:
            return {
                "compliant": False,
                "issues": [f"GDPR check error: {str(e)}"],
                "score": 0
            }

    async def _check_sox_compliance(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Check SOX compliance."""
        try:
            # Simplified SOX compliance check
            audit_logging = parameters.get("audit_logging", False)
            access_controls = parameters.get("access_controls", False)
            data_backup = parameters.get("data_backup", False)
            change_management = parameters.get("change_management", False)

            issues = []
            compliant = True

            if not audit_logging:
                issues.append("Comprehensive audit logging not enabled")
                compliant = False

            if not access_controls:
                issues.append("Strong access controls not implemented")
                compliant = False

            if not data_backup:
                issues.append("Data backup procedures not in place")
                compliant = False

            if not change_management:
                issues.append("Change management process not documented")
                compliant = False

            return {
                "compliant": compliant,
                "issues": issues,
                "score": 90 if compliant else 50
            }

        except Exception as e:
            return {
                "compliant": False,
                "issues": [f"SOX check error: {str(e)}"],
                "score": 0
            }

    async def _check_hipaa_compliance(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Check HIPAA compliance."""
        try:
            # Simplified HIPAA compliance check
            phi_encryption = parameters.get("phi_encryption", False)
            access_logging = parameters.get("access_logging", False)
            data_minimization = parameters.get("data_minimization", False)
            breach_notification = parameters.get("breach_notification", False)

            issues = []
            compliant = True

            if not phi_encryption:
                issues.append("PHI encryption not enabled")
                compliant = False

            if not access_logging:
                issues.append("Access logging not implemented")
                compliant = False

            if not data_minimization:
                issues.append("Data minimization practices not followed")
                compliant = False

            if not breach_notification:
                issues.append("Breach notification procedures not in place")
                compliant = False

            return {
                "compliant": compliant,
                "issues": issues,
                "score": 88 if compliant else 42
            }

        except Exception as e:
            return {
                "compliant": False,
                "issues": [f"HIPAA check error: {str(e)}"],
                "score": 0
            }

    async def get_security_analytics(
        self,
        user_id: Optional[str] = None,
        date_range: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get security and compliance analytics."""
        try:
            # Filter audit logs
            filtered_logs = []
            for uid, logs in self.audit_logs.items():
                if user_id and uid != user_id:
                    continue
                filtered_logs.extend(logs)

            # Filter by date range
            end_date = datetime.now()
            if date_range == "last_7_days":
                start_date = end_date - timedelta(days=7)
            elif date_range == "last_30_days":
                start_date = end_date - timedelta(days=30)
            else:
                start_date = end_date - timedelta(days=30)

            filtered_logs = [
                log for log in filtered_logs
                if start_date <= datetime.fromisoformat(log["timestamp"]) <= end_date
            ]

            # Calculate analytics
            total_events = len(filtered_logs)
            allowed_events = len([log for log in filtered_logs if log["allowed"]])
            blocked_events = len([log for log in filtered_logs if not log["allowed"]])
            
            compliance_score = (allowed_events / total_events * 100) if total_events > 0 else 100

            # Group by action type
            action_stats = {}
            for log in filtered_logs:
                action = log["action"]
                if action not in action_stats:
                    action_stats[action] = {"total": 0, "allowed": 0, "blocked": 0}
                
                action_stats[action]["total"] += 1
                if log["allowed"]:
                    action_stats[action]["allowed"] += 1
                else:
                    action_stats[action]["blocked"] += 1

            analytics = {
                "total_events": total_events,
                "allowed_events": allowed_events,
                "blocked_events": blocked_events,
                "compliance_score": round(compliance_score, 2),
                "action_stats": action_stats,
                "active_policies": len([p for p in self.security_policies.values() if p["status"] == "active"]),
                "encryption_keys": len(self.encryption_keys),
                "date_range": {
                    "start": start_date.strftime("%Y-%m-%d"),
                    "end": end_date.strftime("%Y-%m-%d")
                }
            }

            return {
                "success": True,
                "analytics": analytics
            }

        except Exception as e:
            logger.error(f"Error getting security analytics: {e}")
            return {
                "success": False,
                "error": str(e)
            } 