"""
Multi-tenant architecture service for Mini-Hub MCP Server.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class MultiTenantService:
    """Multi-tenant architecture and resource management service."""

    def __init__(self):
        self.tenants = {}  # In-memory storage for tenants
        self.tenant_resources = {}  # In-memory storage for tenant resources
        self.tenant_configs = {}  # In-memory storage for tenant configurations
        self.tenant_quotas = {}  # In-memory storage for tenant quotas

    async def create_tenant(
        self,
        tenant_name: str,
        admin_email: str,
        plan: str = "basic",
        custom_domain: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new tenant."""
        try:
            tenant_id = str(uuid4())

            tenant = {
                "id": tenant_id,
                "name": tenant_name,
                "admin_email": admin_email,
                "plan": plan,
                "custom_domain": custom_domain,
                "status": "active",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "subscription_end": None,
                "features": self._get_plan_features(plan)
            }

            self.tenants[tenant_id] = tenant

            # Initialize tenant resources
            await self._initialize_tenant_resources(tenant_id, plan)

            # Initialize tenant configuration
            await self._initialize_tenant_config(tenant_id)

            logger.info(f"Created tenant {tenant_id}: {tenant_name}")

            return {
                "success": True,
                "tenant_id": tenant_id,
                "tenant": tenant
            }

        except Exception as e:
            logger.error(f"Error creating tenant: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def _initialize_tenant_resources(self, tenant_id: str, plan: str):
        """Initialize resources for a new tenant."""
        try:
            # Set resource quotas based on plan
            quotas = self._get_plan_quotas(plan)
            
            tenant_resources = {
                "tenant_id": tenant_id,
                "quotas": quotas,
                "usage": {
                    "api_calls": 0,
                    "storage_mb": 0,
                    "users": 0,
                    "integrations": 0,
                    "workflows": 0
                },
                "limits": quotas,
                "created_at": datetime.now().isoformat()
            }

            self.tenant_resources[tenant_id] = tenant_resources

        except Exception as e:
            logger.error(f"Error initializing tenant resources: {e}")

    async def _initialize_tenant_config(self, tenant_id: str):
        """Initialize configuration for a new tenant."""
        try:
            tenant_config = {
                "tenant_id": tenant_id,
                "settings": {
                    "timezone": "UTC",
                    "date_format": "YYYY-MM-DD",
                    "currency": "USD",
                    "language": "en",
                    "notifications": {
                        "email": True,
                        "slack": False,
                        "webhook": False
                    }
                },
                "integrations": {},
                "custom_fields": {},
                "workflows": {},
                "created_at": datetime.now().isoformat()
            }

            self.tenant_configs[tenant_id] = tenant_config

        except Exception as e:
            logger.error(f"Error initializing tenant config: {e}")

    def _get_plan_features(self, plan: str) -> List[str]:
        """Get features available for a plan."""
        plan_features = {
            "basic": [
                "hubspot_integration",
                "ga4_basic_reports",
                "slack_basic_messaging",
                "email_support"
            ],
            "pro": [
                "hubspot_full_integration",
                "ga4_advanced_reports",
                "slack_rich_messaging",
                "priority_support",
                "custom_workflows",
                "api_access"
            ],
            "enterprise": [
                "all_pro_features",
                "white_label",
                "custom_integrations",
                "dedicated_support",
                "advanced_analytics",
                "multi_user_access"
            ]
        }
        return plan_features.get(plan, [])

    def _get_plan_quotas(self, plan: str) -> Dict[str, int]:
        """Get resource quotas for a plan."""
        plan_quotas = {
            "basic": {
                "api_calls_per_day": 1000,
                "storage_mb": 100,
                "users": 1,
                "integrations": 3,
                "workflows": 5
            },
            "pro": {
                "api_calls_per_day": 10000,
                "storage_mb": 1000,
                "users": 5,
                "integrations": 10,
                "workflows": 50
            },
            "enterprise": {
                "api_calls_per_day": 100000,
                "storage_mb": 10000,
                "users": 50,
                "integrations": 100,
                "workflows": 500
            }
        }
        return plan_quotas.get(plan, {})

    async def get_tenant_info(self, tenant_id: str) -> Dict[str, Any]:
        """Get tenant information and status."""
        try:
            if tenant_id not in self.tenants:
                return {
                    "success": False,
                    "error": f"Tenant {tenant_id} not found"
                }

            tenant = self.tenants[tenant_id]
            resources = self.tenant_resources.get(tenant_id, {})
            config = self.tenant_configs.get(tenant_id, {})

            return {
                "success": True,
                "tenant": tenant,
                "resources": resources,
                "config": config
            }

        except Exception as e:
            logger.error(f"Error getting tenant info: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def update_tenant_plan(
        self,
        tenant_id: str,
        new_plan: str
    ) -> Dict[str, Any]:
        """Update tenant plan and adjust resources accordingly."""
        try:
            if tenant_id not in self.tenants:
                return {
                    "success": False,
                    "error": f"Tenant {tenant_id} not found"
                }

            tenant = self.tenants[tenant_id]
            old_plan = tenant["plan"]

            # Update tenant plan
            tenant["plan"] = new_plan
            tenant["features"] = self._get_plan_features(new_plan)
            tenant["updated_at"] = datetime.now().isoformat()

            # Update resource quotas
            new_quotas = self._get_plan_quotas(new_plan)
            if tenant_id in self.tenant_resources:
                self.tenant_resources[tenant_id]["limits"] = new_quotas

            logger.info(f"Updated tenant {tenant_id} from {old_plan} to {new_plan}")

            return {
                "success": True,
                "tenant_id": tenant_id,
                "old_plan": old_plan,
                "new_plan": new_plan,
                "new_features": tenant["features"]
            }

        except Exception as e:
            logger.error(f"Error updating tenant plan: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def check_tenant_quota(
        self,
        tenant_id: str,
        resource_type: str,
        amount: int = 1
    ) -> Dict[str, Any]:
        """Check if tenant has quota available for a resource."""
        try:
            if tenant_id not in self.tenant_resources:
                return {
                    "success": False,
                    "error": f"Tenant {tenant_id} not found"
                }

            resources = self.tenant_resources[tenant_id]
            usage = resources["usage"]
            limits = resources["limits"]

            current_usage = usage.get(resource_type, 0)
            limit = limits.get(resource_type, 0)

            if current_usage + amount > limit:
                return {
                    "success": True,
                    "allowed": False,
                    "current_usage": current_usage,
                    "limit": limit,
                    "requested": amount
                }

            return {
                "success": True,
                "allowed": True,
                "current_usage": current_usage,
                "limit": limit,
                "remaining": limit - current_usage
            }

        except Exception as e:
            logger.error(f"Error checking tenant quota: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def update_tenant_usage(
        self,
        tenant_id: str,
        resource_type: str,
        amount: int = 1
    ) -> Dict[str, Any]:
        """Update tenant resource usage."""
        try:
            if tenant_id not in self.tenant_resources:
                return {
                    "success": False,
                    "error": f"Tenant {tenant_id} not found"
                }

            resources = self.tenant_resources[tenant_id]
            current_usage = resources["usage"].get(resource_type, 0)
            resources["usage"][resource_type] = current_usage + amount

            return {
                "success": True,
                "new_usage": resources["usage"][resource_type]
            }

        except Exception as e:
            logger.error(f"Error updating tenant usage: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_tenant_analytics(
        self,
        tenant_id: str,
        date_range: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get tenant usage analytics."""
        try:
            if tenant_id not in self.tenants:
                return {
                    "success": False,
                    "error": f"Tenant {tenant_id} not found"
                }

            tenant = self.tenants[tenant_id]
            resources = self.tenant_resources.get(tenant_id, {})

            # Calculate usage percentages
            usage_percentages = {}
            for resource_type, usage in resources.get("usage", {}).items():
                limit = resources.get("limits", {}).get(resource_type, 1)
                percentage = (usage / limit * 100) if limit > 0 else 0
                usage_percentages[resource_type] = round(percentage, 2)

            analytics = {
                "tenant_id": tenant_id,
                "tenant_name": tenant["name"],
                "plan": tenant["plan"],
                "usage": resources.get("usage", {}),
                "limits": resources.get("limits", {}),
                "usage_percentages": usage_percentages,
                "status": tenant["status"],
                "created_at": tenant["created_at"]
            }

            return {
                "success": True,
                "analytics": analytics
            }

        except Exception as e:
            logger.error(f"Error getting tenant analytics: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def create_tenant_integration(
        self,
        tenant_id: str,
        integration_type: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a tenant-specific integration."""
        try:
            if tenant_id not in self.tenants:
                return {
                    "success": False,
                    "error": f"Tenant {tenant_id} not found"
                }

            # Check quota
            quota_check = await self.check_tenant_quota(tenant_id, "integrations")
            if not quota_check["allowed"]:
                return {
                    "success": False,
                    "error": "Integration quota exceeded"
                }

            integration_id = str(uuid4())

            integration = {
                "id": integration_id,
                "tenant_id": tenant_id,
                "type": integration_type,
                "config": config,
                "status": "active",
                "created_at": datetime.now().isoformat(),
                "last_sync": None
            }

            # Add to tenant config
            if tenant_id in self.tenant_configs:
                if "integrations" not in self.tenant_configs[tenant_id]:
                    self.tenant_configs[tenant_id]["integrations"] = {}
                
                self.tenant_configs[tenant_id]["integrations"][integration_id] = integration

            # Update usage
            await self.update_tenant_usage(tenant_id, "integrations")

            return {
                "success": True,
                "integration_id": integration_id,
                "integration": integration
            }

        except Exception as e:
            logger.error(f"Error creating tenant integration: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_tenant_integrations(
        self,
        tenant_id: str
    ) -> Dict[str, Any]:
        """Get all integrations for a tenant."""
        try:
            if tenant_id not in self.tenants:
                return {
                    "success": False,
                    "error": f"Tenant {tenant_id} not found"
                }

            config = self.tenant_configs.get(tenant_id, {})
            integrations = config.get("integrations", {})

            return {
                "success": True,
                "integrations": list(integrations.values())
            }

        except Exception as e:
            logger.error(f"Error getting tenant integrations: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def update_tenant_config(
        self,
        tenant_id: str,
        config_updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update tenant configuration."""
        try:
            if tenant_id not in self.tenants:
                return {
                    "success": False,
                    "error": f"Tenant {tenant_id} not found"
                }

            if tenant_id not in self.tenant_configs:
                return {
                    "success": False,
                    "error": f"Tenant config not found"
                }

            config = self.tenant_configs[tenant_id]
            
            # Update configuration
            for key, value in config_updates.items():
                if key in ["settings", "custom_fields"]:
                    config[key].update(value)
                else:
                    config[key] = value

            config["updated_at"] = datetime.now().isoformat()

            return {
                "success": True,
                "tenant_id": tenant_id,
                "config": config
            }

        except Exception as e:
            logger.error(f"Error updating tenant config: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_all_tenants_summary(self) -> Dict[str, Any]:
        """Get summary of all tenants."""
        try:
            tenants_summary = []
            
            for tenant_id, tenant in self.tenants.items():
                resources = self.tenant_resources.get(tenant_id, {})
                
                summary = {
                    "tenant_id": tenant_id,
                    "name": tenant["name"],
                    "plan": tenant["plan"],
                    "status": tenant["status"],
                    "created_at": tenant["created_at"],
                    "usage": resources.get("usage", {}),
                    "limits": resources.get("limits", {})
                }
                
                tenants_summary.append(summary)

            return {
                "success": True,
                "total_tenants": len(tenants_summary),
                "tenants": tenants_summary
            }

        except Exception as e:
            logger.error(f"Error getting tenants summary: {e}")
            return {
                "success": False,
                "error": str(e)
            } 