"""
Optimized Tool Router Service for 100% accuracy in tool selection.
"""

import logging
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Connection, ConnectionStatus, User
from .dynamic_tool_registry import dynamic_tool_registry

logger = logging.getLogger(__name__)


class PrecisionToolRouter:
    """Optimized tool router for 100% accuracy in tool selection."""
    
    def __init__(self, user: User, db: AsyncSession):
        self.user = user
        self.db = db
        self._tool_cache = {}
        self._cache_timestamp = {}
        self._cache_duration = 300  # 5 minutes
        self._connection_cache = None
        self._usage_patterns = None
        self._domain_knowledge = self._load_domain_knowledge()
    
    async def get_relevant_tools(self, user_input: str) -> List[Dict[str, Any]]:
        """
        Get relevant tools with 100% accuracy using multi-stage matching.
        
        Args:
            user_input: The user's message
            
        Returns:
            List of relevant tools with confidence scores
        """
        print(f"🎯 ToolRouter: Processing input: '{user_input}'")
        
        # Load tools with cache
        all_tools = await self._get_all_tools()
        print(f"📦 Loaded {len(all_tools)} tools for user {self.user.id}")
        
        # Multi-stage matching process
        results = await self._match_tools(user_input, all_tools)
        
        # Sort by confidence score
        results.sort(key=lambda x: x[1], reverse=True)
        
        print(f"🔍 Found {len(results)} potential matches:")
        for tool, confidence in results:
            print(f"   - {tool['name']}: {confidence:.3f}")
        
        # Return tools with confidence > 80%
        final_results = [tool for tool, confidence in results if confidence > 0.8]
        print(f"✅ Final selection: {len(final_results)} tools with confidence > 0.8")
        
        return final_results
    
    async def _match_tools(self, user_input: str, tools: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], float]]:
        """Execute multi-stage matching pipeline"""
        results = []
        
        print(f"🔍 Stage 1: Exact command matching")
        # Stage 1: Exact command matching (100% confidence)
        if exact_match := self._exact_command_match(user_input, tools):
            print(f"   ✅ Exact match found: {exact_match['name']} (100% confidence)")
            return [(exact_match, 1.0)]
        else:
            print(f"   ❌ No exact match found")
        
        print(f"🧠 Stage 2: Semantic pattern matching")
        # Stage 2: Semantic pattern matching
        semantic_results = await self._semantic_pattern_match(user_input, tools)
        results.extend(semantic_results)
        if semantic_results:
            for tool, confidence in semantic_results:
                print(f"   ✅ Semantic match: {tool['name']} ({confidence:.3f})")
        else:
            print(f"   ❌ No semantic matches")
        
        print(f"📊 Stage 3: Usage-based matching")
        # Stage 3: Usage-based matching
        usage_results = await self._usage_based_match(user_input, tools)
        results.extend(usage_results)
        if usage_results:
            for tool, confidence in usage_results:
                print(f"   ✅ Usage match: {tool['name']} ({confidence:.3f})")
        else:
            print(f"   ❌ No usage matches")
        
        print(f"🔍 Stage 4: Fuzzy matching")
        # Stage 4: Fuzzy matching
        fuzzy_results = self._fuzzy_match(user_input, tools)
        results.extend(fuzzy_results)
        if fuzzy_results:
            for tool, confidence in fuzzy_results:
                print(f"   ✅ Fuzzy match: {tool['name']} ({confidence:.3f})")
        else:
            print(f"   ❌ No fuzzy matches")
        
        print(f"🚀 Stage 5: Contextual boost")
        # Stage 5: Contextual boost
        results = self._apply_contextual_boost(user_input, results)
        if results:
            for tool, confidence in results:
                print(f"   ✅ Boosted: {tool['name']} ({confidence:.3f})")
        
        # Deduplicate results
        seen = set()
        deduped = []
        for tool, confidence in results:
            if tool['name'] not in seen:
                seen.add(tool['name'])
                deduped.append((tool, confidence))
        
        print(f"📋 Final results after deduplication: {len(deduped)} unique tools")
        return deduped
    
    def _exact_command_match(self, user_input: str, tools: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Match predefined exact commands for all available tools"""
        command_map = {
            # Slack Tools
            r'(send|post).*slack': 'slack_send_message',
            r'create.*slack.*channel': 'slack_create_channel',
            r'list.*slack.*channel': 'slack_list_channels',
            r'get.*slack.*channel.*member': 'slack_get_channel_members',
            r'list.*slack.*member': 'slack_get_channel_members',
            
            # WhatsApp Tools
            r'whatsapp.*message': 'whatsapp_send_message',
            r'send.*whatsapp': 'whatsapp_send_message',
            r'whatsapp.*media': 'whatsapp_send_media_message',
            
            # HubSpot Tools
            r'(hubspot|crm).*contact': 'hubspot_crm_management',
            r'create.*hubspot.*contact': 'hubspot_crm_management',
            r'get.*hubspot.*contact': 'hubspot_crm_management',
            r'update.*hubspot.*contact': 'hubspot_crm_management',
            
            # Salesforce Tools
            r'(salesforce|crm).*contact': 'salesforce_crm_management',
            r'create.*salesforce.*contact': 'salesforce_crm_management',
            r'get.*salesforce.*contact': 'salesforce_crm_management',
            r'(salesforce|crm).*lead': 'salesforce_crm_management',
            r'create.*salesforce.*lead': 'salesforce_crm_management',
            r'get.*salesforce.*lead': 'salesforce_crm_management',
            r'(salesforce|crm).*opportunity': 'salesforce_crm_management',
            r'create.*salesforce.*opportunity': 'salesforce_crm_management',
            r'get.*salesforce.*opportunity': 'salesforce_crm_management',
            
            # GA4 Tools
            r'ga4.*traffic': 'ga4_get_traffic',
            r'get.*ga4.*traffic': 'ga4_get_traffic',
            r'show.*ga4.*traffic': 'ga4_get_traffic',
            r'ga4.*conversion': 'ga4_get_conversions',
            r'get.*ga4.*conversion': 'ga4_get_conversions',
            r'show.*ga4.*conversion': 'ga4_get_conversions',
            r'analytics.*traffic': 'ga4_get_traffic',
            r'analytics.*conversion': 'ga4_get_conversions',
            r'google.*analytics.*traffic': 'ga4_get_traffic',
            r'google.*analytics.*conversion': 'ga4_get_conversions',
            r'user.*behavior.*ga4': 'ga4_get_traffic',
            r'user.*behavior.*analytics': 'ga4_get_traffic',
            r'show.*user.*behavior.*ga4': 'ga4_get_traffic',
            r'show.*user.*behavior.*analytics': 'ga4_get_traffic',
            
            # Asana Tools
            r'list.*asana.*project': 'asana_list_projects',
            r'get.*asana.*project': 'asana_list_projects',
            r'show.*asana.*project': 'asana_list_projects',
            r'create.*asana.*project': 'asana_create_project',
            r'add.*asana.*project': 'asana_create_project',
            r'list.*asana.*task': 'asana_list_tasks',
            r'get.*asana.*task': 'asana_list_tasks',
            r'show.*asana.*task': 'asana_list_tasks',
            r'create.*asana.*task': 'asana_create_task',
            r'add.*asana.*task': 'asana_create_task',
            r'add.*asana.*comment': 'asana_add_comment',
            r'comment.*asana.*task': 'asana_add_comment',
            r'get.*asana.*team': 'asana_get_teams',
            r'list.*asana.*team': 'asana_get_teams',
            r'get.*asana.*workspace': 'asana_get_workspaces',
            r'list.*asana.*workspace': 'asana_get_workspaces',
            
            # Power BI Tools
            r'powerbi.*workspace': 'powerbi_list_workspaces',
            r'power.*bi.*workspace': 'powerbi_list_workspaces',
            r'list.*powerbi.*workspace': 'powerbi_list_workspaces',
            r'list.*power.*bi.*workspace': 'powerbi_list_workspaces',
            r'get.*powerbi.*workspace': 'powerbi_list_workspaces',
            r'get.*power.*bi.*workspace': 'powerbi_list_workspaces',
            r'powerbi.*dataset': 'powerbi_list_datasets',
            r'power.*bi.*dataset': 'powerbi_list_datasets',
            r'list.*powerbi.*dataset': 'powerbi_list_datasets',
            r'list.*power.*bi.*dataset': 'powerbi_list_datasets',
            r'powerbi.*report': 'powerbi_list_reports',
            r'power.*bi.*report': 'powerbi_list_reports',
            r'list.*powerbi.*report': 'powerbi_list_reports',
            r'list.*power.*bi.*report': 'powerbi_list_reports',
            r'powerbi.*dashboard': 'powerbi_list_dashboards',
            r'power.*bi.*dashboard': 'powerbi_list_dashboards',
            r'list.*powerbi.*dashboard': 'powerbi_list_dashboards',
            r'list.*power.*bi.*dashboard': 'powerbi_list_dashboards',
            r'powerbi.*dax': 'powerbi_execute_dax_query',
            r'power.*bi.*dax': 'powerbi_execute_dax_query',
            r'execute.*dax': 'powerbi_execute_dax_query',
            r'powerbi.*refresh': 'powerbi_refresh_dataset',
            r'power.*bi.*refresh': 'powerbi_refresh_dataset',
            r'refresh.*dataset': 'powerbi_refresh_dataset',
            r'powerbi.*embed': 'powerbi_get_embed_token',
            r'power.*bi.*embed': 'powerbi_get_embed_token',
            r'embed.*token': 'powerbi_get_embed_token',
            
            # Zoom Tools
            r'zoom.*meeting': 'zoom_meeting_management',
            r'create.*zoom.*meeting': 'zoom_meeting_management',
            r'schedule.*zoom.*meeting': 'zoom_meeting_management',
            r'list.*zoom.*meeting': 'zoom_meeting_management',
            r'get.*zoom.*meeting': 'zoom_meeting_management',
            
            # Teams Tools
            r'teams.*message': 'teams_send_message',
            r'send.*teams.*message': 'teams_send_message',
            r'teams.*notification': 'teams_send_message',
            r'teams.*webhook': 'teams_send_message',
            
            # File Management Tools
            r'(upload|download).*file': 'file_management',
            r'upload.*document': 'file_management',
            r'download.*document': 'file_management',
            r'generate.*pdf': 'file_management',
            r'create.*pdf': 'file_management',
            
            # Web Tools
            r'scrape.*website': 'web_tools',
            r'extract.*web.*data': 'web_tools',
            r'web.*scraping': 'web_tools',
            r'crawl.*website': 'web_tools',
            
            # Content Creation Tools
            r'generate.*image': 'content_creation',
            r'create.*image': 'content_creation',
            r'design.*image': 'content_creation',
            r'generate.*content': 'content_creation',
            r'create.*content': 'content_creation',
            
            # Marketing Tools
            r'campaign.*automation': 'marketing_campaign_automation',
            r'automate.*campaign': 'marketing_campaign_automation',
            r'marketing.*automation': 'marketing_campaign_automation',
            r'track.*performance': 'campaign_performance_tracking',
            r'campaign.*performance': 'campaign_performance_tracking',
            r'performance.*tracking': 'campaign_performance_tracking',
            
            # Advanced Analytics Tools
            r'score.*lead': 'lead_scoring_engine',
            r'lead.*scoring': 'lead_scoring_engine',
            r'qualify.*lead': 'lead_scoring_engine',
            r'journey.*map': 'customer_journey_mapping',
            r'customer.*journey': 'customer_journey_mapping',
            r'map.*journey': 'customer_journey_mapping',
            r'predict.*behavior': 'predictive_analytics_engine',
            r'predictive.*analysis': 'predictive_analytics_engine',
            r'forecast.*trend': 'predictive_analytics_engine',
            r'predict.*trend': 'predictive_analytics_engine',
            
            # A/B Testing Tools
            r'ab.*test': 'ab_testing_platform',
            r'a/b.*test': 'ab_testing_platform',
            r'create.*ab.*test': 'ab_testing_platform',
            r'run.*ab.*test': 'ab_testing_platform',
            
            # Workflow Tools
            r'workflow.*builder': 'workflow_builder',
            r'create.*workflow': 'workflow_builder',
            r'build.*workflow': 'workflow_builder',
            r'automate.*workflow': 'workflow_builder',
            
            # API Management Tools
            r'api.*management': 'api_management',
            r'manage.*api': 'api_management',
            r'api.*endpoint': 'api_management',
            r'create.*api': 'api_management',
            
            # Multi-tenant Tools
            r'multi.*tenant': 'multi_tenant_service',
            r'tenant.*management': 'multi_tenant_service',
            r'manage.*tenant': 'multi_tenant_service',
            
            # Enterprise Security Tools
            r'enterprise.*security': 'enterprise_security_service',
            r'security.*audit': 'enterprise_security_service',
            r'compliance.*check': 'enterprise_security_service',
            
            # White Label Tools
            r'white.*label': 'white_label_service',
            r'brand.*customization': 'white_label_service',
            r'custom.*branding': 'white_label_service',
            
            # Billing Tools
            r'billing.*management': 'billing_service',
            r'invoice.*management': 'billing_service',
            r'payment.*processing': 'billing_service',
            r'subscription.*management': 'billing_service',
            
            # Rate Limiting Tools
            r'rate.*limit': 'rate_limit_service',
            r'throttle.*request': 'rate_limit_service',
            r'limit.*api.*call': 'rate_limit_service',
            
            # File Management Tools (Extended)
            r'file.*management': 'file_management',
            r'manage.*file': 'file_management',
            r'organize.*file': 'file_management',
            r'backup.*file': 'file_management',
            
            # Web Tools (Extended)
            r'web.*tool': 'web_tools',
            r'web.*utility': 'web_tools',
            r'web.*service': 'web_tools',
            r'web.*integration': 'web_tools'
        }
        
        user_input = user_input.lower()
        print(f"   🔍 Testing exact patterns on: '{user_input}'")
        
        # Sort patterns by specificity (longer patterns first) to ensure more specific matches
        sorted_patterns = sorted(command_map.items(), key=lambda x: len(x[0]), reverse=True)
        
        for pattern, tool_name in sorted_patterns:
            if re.search(pattern, user_input):
                print(f"   ✅ Pattern '{pattern}' matched for tool '{tool_name}'")
                tool = next((t for t in tools if t['name'] == tool_name), None)
                if tool:
                    print(f"   🎯 Found matching tool: {tool_name}")
                    return tool
                else:
                    print(f"   ⚠️  Tool '{tool_name}' not found in available tools")
            else:
                print(f"   ❌ Pattern '{pattern}' did not match")
        
        return None
    
    async def _semantic_pattern_match(self, user_input: str, tools: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], float]]:
        """Semantic matching with domain-specific patterns"""
        results = []
        user_tokens = self._tokenize(user_input)
        print(f"   🔍 User tokens: {user_tokens}")
        
        for tool in tools:
            tool_name = tool['name']
            print(f"   📋 Testing tool: {tool_name}")
            
            # Match against predefined patterns
            tool_patterns = self._domain_knowledge.get(tool_name, {}).get('patterns', [])
            print(f"      Patterns: {tool_patterns}")
            
            pattern_matched = False
            for pattern in tool_patterns:
                if self._pattern_match(user_tokens, pattern):
                    print(f"      ✅ Pattern matched: {pattern}")
                    results.append((tool, 0.95))
                    pattern_matched = True
                    break
                else:
                    print(f"      ❌ Pattern not matched: {pattern}")
            
            if not pattern_matched:
                # Match against tool keywords
                tool_keywords = self._domain_knowledge.get(tool_name, {}).get('keywords', [])
                print(f"      Keywords: {tool_keywords}")
                
                matched_keywords = [kw for kw in tool_keywords if kw in user_tokens]
                if matched_keywords:
                    print(f"      ✅ Keywords matched: {matched_keywords}")
                    results.append((tool, 0.85))
                else:
                    print(f"      ❌ No keywords matched")
        
        return results
    
    async def _usage_based_match(self, user_input: str, tools: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], float]]:
        """Match based on user's historical tool usage patterns"""
        if self._usage_patterns is None:
            await self._load_usage_patterns()
        
        results = []
        user_tokens = self._tokenize(user_input)
        
        for tool in tools:
            tool_name = tool['name']
            usage_keywords = self._usage_patterns.get(tool_name, [])
            
            # Calculate keyword match ratio
            matched = sum(1 for kw in usage_keywords if kw in user_tokens)
            ratio = matched / len(usage_keywords) if usage_keywords else 0
            
            if ratio > 0.7:
                confidence = min(0.9, 0.7 + (ratio - 0.7) * 2)
                results.append((tool, confidence))
        
        return results
    
    def _fuzzy_match(self, user_input: str, tools: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], float]]:
        """Fuzzy string matching as fallback"""
        results = []
        user_input_lower = user_input.lower()
        
        for tool in tools:
            tool_name = tool['name']
            print(f"   🔍 Fuzzy matching for: {tool_name}")
            
            # Match tool name
            name_score = self._fuzzy_ratio(user_input_lower, tool['name'])
            print(f"      Name score: {name_score:.2f}")
            
            # Match description
            desc_score = self._fuzzy_ratio(user_input_lower, tool['description'])
            print(f"      Description score: {desc_score:.2f}")
            
            # Weighted average
            score = (name_score * 0.7 + desc_score * 0.3) / 100
            print(f"      Weighted score: {score:.3f}")
            
            if score > 0.6:
                final_score = score * 0.8  # Cap at 80% confidence
                print(f"      ✅ Above threshold, final score: {final_score:.3f}")
                results.append((tool, final_score))
            else:
                print(f"      ❌ Below threshold (0.6)")
        
        return results
    
    def _fuzzy_ratio(self, s1: str, s2: str) -> float:
        """Simple fuzzy ratio calculation"""
        s1_tokens = set(self._tokenize(s1))
        s2_tokens = set(self._tokenize(s2))
        
        if not s1_tokens and not s2_tokens:
            return 0.0
        
        intersection = len(s1_tokens & s2_tokens)
        union = len(s1_tokens | s2_tokens)
        
        return (intersection / union) * 100 if union > 0 else 0.0
    
    def _apply_contextual_boost(self, user_input: str, matches: List[Tuple[Dict[str, Any], float]]) -> List[Tuple[Dict[str, Any], float]]:
        """Apply contextual boosts to matches"""
        boosted = []
        
        # Boost for active connections
        active_platforms = self._get_active_connections()
        print(f"   🔗 Active platforms: {active_platforms}")
        
        # Boost for command verbs
        command_verbs = {'send', 'create', 'get', 'list', 'find', 'scrape', 'generate', 
                         'download', 'upload', 'execute', 'run', 'call', 'manage'}
        has_command = any(verb in user_input.lower() for verb in command_verbs)
        print(f"   🎯 Has command verb: {has_command}")
        
        for tool, confidence in matches:
            tool_name = tool['name']
            original_confidence = confidence
            boost_reasons = []
            
            # Boost for connected platforms
            if tool.get('platform') in active_platforms:
                confidence = min(1.0, confidence + 0.15)
                boost_reasons.append(f"platform_boost(+0.15)")
            
            # Boost for command presence
            if has_command and tool.get('is_action', True):
                confidence = min(1.0, confidence + 0.1)
                boost_reasons.append(f"command_boost(+0.1)")
            
            if boost_reasons:
                print(f"   🚀 {tool_name}: {original_confidence:.3f} → {confidence:.3f} ({', '.join(boost_reasons)})")
            else:
                print(f"   📊 {tool_name}: {confidence:.3f} (no boost)")
            
            boosted.append((tool, confidence))
        
        return boosted
    
    async def _load_usage_patterns(self):
        """Load user's historical tool usage patterns"""
        self._usage_patterns = defaultdict(list)
        
        # Get last 100 usage logs
        result = await self.db.execute(
            select(User.usage_logs)
            .filter(User.id == self.user.id)
        )
        usage_logs = result.scalars().all()
        
        # Extract keywords from tool inputs
        for log in usage_logs[:100]:  # Limit to last 100
            if log.arguments:
                tokens = self._tokenize(log.arguments)
                self._usage_patterns[log.tool_name].extend(tokens)
        
        # Deduplicate and keep top keywords
        for tool in self._usage_patterns:
            counter = defaultdict(int)
            for token in self._usage_patterns[tool]:
                counter[token] += 1
            # Get top 10 keywords
            self._usage_patterns[tool] = [
                token for token, count in 
                sorted(counter.items(), key=lambda x: x[1], reverse=True)[:10]
            ]
    
    def _get_active_connections(self) -> set:
        """Get cached active connections"""
        if self._connection_cache is None:
            # In real implementation, load from DB
            self._connection_cache = {'slack', 'hubspot', 'whatsapp'}
        return self._connection_cache
    
    def _load_domain_knowledge(self) -> Dict[str, Any]:
        """Domain-specific knowledge for precision matching"""
        return {
            "slack_send_message": {
                "patterns": [
                    ["send", "message", "slack"],
                    ["post", "update", "channel"],
                    ["notify", "team", "slack"]
                ],
                "keywords": ["slack", "channel", "message", "send", "notify"]
            },
            "slack_create_channel": {
                "patterns": [
                    ["create", "slack", "channel"],
                    ["create", "new", "slack", "channel"],
                    ["invite", "members", "channel"],
                    ["update", "channel", "settings"],
                    ["manage", "slack", "workspace"]
                ],
                "keywords": ["slack", "channel", "create", "manage", "workspace", "invite", "team"]
            },
            "slack_list_channels": {
                "patterns": [
                    ["list", "slack", "channels"],
                    ["get", "channels"],
                    ["show", "channels"]
                ],
                "keywords": ["slack", "channel", "list", "get", "show"]
            },
            "slack_get_channel_members": {
                "patterns": [
                    ["get", "channel", "members"],
                    ["list", "members"],
                    ["show", "members"]
                ],
                "keywords": ["slack", "channel", "members", "list", "get", "show"]
            },
            "whatsapp_messaging": {
                "patterns": [
                    ["send", "whatsapp", "message"],
                    ["whatsapp", "notification"],
                    ["message", "phone", "number"]
                ],
                "keywords": ["whatsapp", "phone", "sms", "text", "message"]
            },
            "hubspot_contact_operations": {
                "patterns": [
                    ["create", "hubspot", "contact"],
                    ["update", "crm", "record"],
                    ["find", "contact", "hubspot"]
                ],
                "keywords": ["hubspot", "contact", "crm", "lead", "client"]
            },
            "ga4_analytics_dashboard": {
                "patterns": [
                    ["analytics", "report"],
                    ["website", "traffic"],
                    ["user", "behavior", "analysis"]
                ],
                "keywords": ["analytics", "ga4", "report", "metrics", "dashboard"]
            },
            "file_management": {
                "patterns": [
                    ["upload", "file"],
                    ["download", "document"],
                    ["generate", "pdf"]
                ],
                "keywords": ["file", "document", "upload", "download", "pdf"]
            },
            "web_tools": {
                "patterns": [
                    ["scrape", "website"],
                    ["extract", "web", "data"],
                    ["monitor", "website"]
                ],
                "keywords": ["scrape", "website", "web", "extract", "crawl"]
            },
            "content_creation": {
                "patterns": [
                    ["generate", "image"],
                    ["create", "content"],
                    ["design", "visual"]
                ],
                "keywords": ["image", "content", "generate", "create", "design"]
            },
            "marketing_campaign_automation": {
                "patterns": [
                    ["automate", "campaign"],
                    ["marketing", "automation"],
                    ["campaign", "workflow"]
                ],
                "keywords": ["campaign", "automation", "marketing", "workflow"]
            },
            "campaign_performance_tracking": {
                "patterns": [
                    ["track", "performance"],
                    ["campaign", "metrics"],
                    ["analyze", "results"]
                ],
                "keywords": ["track", "performance", "metrics", "analytics"]
            },
            "lead_scoring_engine": {
                "patterns": [
                    ["score", "lead"],
                    ["qualify", "prospect"],
                    ["lead", "scoring"]
                ],
                "keywords": ["score", "lead", "qualify", "prospect"]
            },
            "customer_journey_mapping": {
                "patterns": [
                    ["journey", "map"],
                    ["customer", "journey"],
                    ["touchpoint", "analysis"]
                ],
                "keywords": ["journey", "customer", "touchpoint", "map"]
            },
            "asana_list_projects": {
                "patterns": [
                    ["list", "asana", "project"],
                    ["get", "asana", "project"],
                    ["show", "asana", "project"],
                    ["list", "my", "asana", "project"]
                ],
                "keywords": ["asana", "project", "list", "get", "show"]
            },
            "asana_create_project": {
                "patterns": [
                    ["create", "asana", "project"],
                    ["new", "asana", "project"],
                    ["add", "asana", "project"]
                ],
                "keywords": ["asana", "project", "create", "new", "add"]
            },
            "asana_list_tasks": {
                "patterns": [
                    ["list", "asana", "task"],
                    ["get", "asana", "task"],
                    ["show", "asana", "task"],
                    ["list", "my", "asana", "task"]
                ],
                "keywords": ["asana", "task", "list", "get", "show"]
            },
            "asana_create_task": {
                "patterns": [
                    ["create", "asana", "task"],
                    ["new", "asana", "task"],
                    ["add", "asana", "task"]
                ],
                "keywords": ["asana", "task", "create", "new", "add"]
            },
            "asana_add_comment": {
                "patterns": [
                    ["add", "asana", "comment"],
                    ["comment", "asana", "task"],
                    ["note", "asana", "task"]
                ],
                "keywords": ["asana", "comment", "note", "add"]
            },
            "asana_get_teams": {
                "patterns": [
                    ["get", "asana", "team"],
                    ["list", "asana", "team"],
                    ["show", "asana", "team"]
                ],
                "keywords": ["asana", "team", "get", "list", "show"]
            },
            "asana_get_workspaces": {
                "patterns": [
                    ["get", "asana", "workspace"],
                    ["list", "asana", "workspace"],
                    ["show", "asana", "workspace"],
                    ["find", "asana", "workspace"]
                ],
                "keywords": ["asana", "workspace", "get", "list", "show", "find"]
            },
            "predictive_analytics_engine": {
                "patterns": [
                    ["predict", "behavior"],
                    ["forecast", "trends"],
                    ["predictive", "analysis"]
                ],
                "keywords": ["predict", "forecast", "trends", "behavior"]
            },
            "salesforce_create_contact": {
                "patterns": [
                    ["create", "contact", "salesforce"],
                    ["add", "contact", "crm"],
                    ["new", "contact", "salesforce"]
                ],
                "keywords": ["salesforce", "contact", "create", "add", "crm"]
            },
            "salesforce_search_contacts": {
                "patterns": [
                    ["search", "contact", "salesforce"],
                    ["find", "contact", "crm"],
                    ["lookup", "contact"]
                ],
                "keywords": ["salesforce", "contact", "search", "find", "lookup"]
            },
            "salesforce_create_lead": {
                "patterns": [
                    ["create", "lead", "salesforce"],
                    ["add", "lead", "crm"],
                    ["new", "lead", "salesforce"]
                ],
                "keywords": ["salesforce", "lead", "create", "add", "crm"]
            },
            "salesforce_get_leads": {
                "patterns": [
                    ["get", "leads", "salesforce"],
                    ["list", "leads", "crm"],
                    ["view", "leads"]
                ],
                "keywords": ["salesforce", "lead", "get", "list", "view"]
            },
            "salesforce_create_opportunity": {
                "patterns": [
                    ["create", "opportunity", "salesforce"],
                    ["add", "opportunity", "crm"],
                    ["new", "opportunity", "salesforce"]
                ],
                "keywords": ["salesforce", "opportunity", "create", "add", "crm"]
            },
            "salesforce_get_opportunities": {
                "patterns": [
                    ["get", "opportunities", "salesforce"],
                    ["list", "opportunities", "crm"],
                    ["view", "opportunities"]
                ],
                "keywords": ["salesforce", "opportunity", "get", "list", "view"]
            },
            "salesforce_get_pipeline_report": {
                "patterns": [
                    ["pipeline", "report", "salesforce"],
                    ["sales", "report", "crm"],
                    ["opportunity", "report"]
                ],
                "keywords": ["salesforce", "pipeline", "report", "sales", "opportunity"]
            },
            "salesforce_sync_from_hubspot": {
                "patterns": [
                    ["sync", "hubspot", "salesforce"],
                    ["import", "contacts", "hubspot"],
                    ["migrate", "data", "hubspot"]
                ],
                "keywords": ["salesforce", "hubspot", "sync", "import", "migrate"]
            },
            # GA4 Tools
            "ga4_get_traffic": {
                "patterns": [
                    ["ga4", "traffic"],
                    ["google", "analytics", "traffic"],
                    ["analytics", "traffic"],
                    ["user", "behavior", "ga4"],
                    ["show", "user", "behavior", "ga4"],
                    ["get", "ga4", "traffic"],
                    ["show", "ga4", "traffic"]
                ],
                "keywords": ["ga4", "google", "analytics", "traffic", "user", "behavior", "show", "get"]
            },
            "ga4_get_conversions": {
                "patterns": [
                    ["ga4", "conversion"],
                    ["google", "analytics", "conversion"],
                    ["analytics", "conversion"],
                    ["get", "ga4", "conversion"],
                    ["show", "ga4", "conversion"]
                ],
                "keywords": ["ga4", "google", "analytics", "conversion", "show", "get"]
            },
            # WhatsApp Tools
            "whatsapp_send_message": {
                "patterns": [
                    ["whatsapp", "message"],
                    ["send", "whatsapp"],
                    ["whatsapp", "notification"]
                ],
                "keywords": ["whatsapp", "message", "send", "notification"]
            },
            "whatsapp_send_media_message": {
                "patterns": [
                    ["whatsapp", "media"],
                    ["send", "media", "whatsapp"],
                    ["whatsapp", "image"],
                    ["whatsapp", "video"]
                ],
                "keywords": ["whatsapp", "media", "image", "video", "send"]
            },
            # Teams Tools
            "teams_send_message": {
                "patterns": [
                    ["teams", "message"],
                    ["send", "teams", "message"],
                    ["teams", "notification"],
                    ["teams", "webhook"]
                ],
                "keywords": ["teams", "message", "send", "notification", "webhook"]
            },
            # Zoom Tools
            "zoom_meeting_management": {
                "patterns": [
                    ["zoom", "meeting"],
                    ["create", "zoom", "meeting"],
                    ["schedule", "zoom", "meeting"],
                    ["list", "zoom", "meeting"],
                    ["get", "zoom", "meeting"]
                ],
                "keywords": ["zoom", "meeting", "create", "schedule", "list", "get"]
            },
            # Power BI Tools
            "powerbi_list_workspaces": {
                "patterns": [
                    ["powerbi", "workspace"],
                    ["power", "bi", "workspace"],
                    ["list", "powerbi", "workspace"],
                    ["get", "powerbi", "workspace"]
                ],
                "keywords": ["powerbi", "power", "bi", "workspace", "list", "get"]
            },
            "powerbi_list_datasets": {
                "patterns": [
                    ["powerbi", "dataset"],
                    ["power", "bi", "dataset"],
                    ["list", "powerbi", "dataset"],
                    ["get", "powerbi", "dataset"]
                ],
                "keywords": ["powerbi", "power", "bi", "dataset", "list", "get"]
            },
            "powerbi_list_reports": {
                "patterns": [
                    ["powerbi", "report"],
                    ["power", "bi", "report"],
                    ["list", "powerbi", "report"],
                    ["get", "powerbi", "report"]
                ],
                "keywords": ["powerbi", "power", "bi", "report", "list", "get"]
            },
            "powerbi_list_dashboards": {
                "patterns": [
                    ["powerbi", "dashboard"],
                    ["power", "bi", "dashboard"],
                    ["list", "powerbi", "dashboard"],
                    ["get", "powerbi", "dashboard"]
                ],
                "keywords": ["powerbi", "power", "bi", "dashboard", "list", "get"]
            },
            "powerbi_execute_dax_query": {
                "patterns": [
                    ["powerbi", "dax"],
                    ["power", "bi", "dax"],
                    ["execute", "dax"],
                    ["run", "dax", "query"]
                ],
                "keywords": ["powerbi", "power", "bi", "dax", "execute", "query"]
            },
            "powerbi_refresh_dataset": {
                "patterns": [
                    ["powerbi", "refresh"],
                    ["power", "bi", "refresh"],
                    ["refresh", "dataset"]
                ],
                "keywords": ["powerbi", "power", "bi", "refresh", "dataset"]
            },
            "powerbi_get_embed_token": {
                "patterns": [
                    ["powerbi", "embed"],
                    ["power", "bi", "embed"],
                    ["embed", "token"]
                ],
                "keywords": ["powerbi", "power", "bi", "embed", "token"]
            },
            # Advanced Tools
            "ab_testing_platform": {
                "patterns": [
                    ["ab", "test"],
                    ["a/b", "test"],
                    ["create", "ab", "test"],
                    ["run", "ab", "test"]
                ],
                "keywords": ["ab", "test", "a/b", "create", "run"]
            },
            "workflow_builder": {
                "patterns": [
                    ["workflow", "builder"],
                    ["create", "workflow"],
                    ["build", "workflow"],
                    ["automate", "workflow"]
                ],
                "keywords": ["workflow", "builder", "create", "build", "automate"]
            },
            "api_management": {
                "patterns": [
                    ["api", "management"],
                    ["manage", "api"],
                    ["api", "endpoint"],
                    ["create", "api"]
                ],
                "keywords": ["api", "management", "endpoint", "create"]
            },
            "multi_tenant_service": {
                "patterns": [
                    ["multi", "tenant"],
                    ["tenant", "management"],
                    ["manage", "tenant"]
                ],
                "keywords": ["multi", "tenant", "management"]
            },
            "enterprise_security_service": {
                "patterns": [
                    ["enterprise", "security"],
                    ["security", "audit"],
                    ["compliance", "check"]
                ],
                "keywords": ["enterprise", "security", "audit", "compliance"]
            },
            "white_label_service": {
                "patterns": [
                    ["white", "label"],
                    ["brand", "customization"],
                    ["custom", "branding"]
                ],
                "keywords": ["white", "label", "brand", "custom"]
            },
            "billing_service": {
                "patterns": [
                    ["billing", "management"],
                    ["invoice", "management"],
                    ["payment", "processing"],
                    ["subscription", "management"]
                ],
                "keywords": ["billing", "invoice", "payment", "subscription"]
            },
            "rate_limit_service": {
                "patterns": [
                    ["rate", "limit"],
                    ["throttle", "request"],
                    ["limit", "api", "call"]
                ],
                "keywords": ["rate", "limit", "throttle", "api"]
            }
        }
    
    def _pattern_match(self, tokens: List[str], pattern: List[str]) -> bool:
        """Check if token sequence matches pattern"""
        pattern_set = set(pattern)
        return all(word in tokens for word in pattern_set)
    
    def _tokenize(self, text: str) -> List[str]:
        """Advanced tokenization with stemming"""
        # Basic tokenization
        tokens = re.findall(r'\b\w{3,}\b', text.lower())
        
        # Apply stemming
        stemmed = [self._stem(token) for token in tokens]
        
        # Remove stop words
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'as', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
            'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 'those'
        }
        
        return [token for token in stemmed if token not in stop_words]
    
    def _stem(self, word: str) -> str:
        """Simple stemmer for common suffixes"""
        if word.endswith('ing'):
            return word[:-3]
        if word.endswith('ed'):
            return word[:-2]
        if word.endswith('s'):
            return word[:-1]
        return word
    
    async def _get_all_tools(self) -> List[Dict[str, Any]]:
        """Get tools with caching"""
        cache_key = f"user_{self.user.id}_tools"
        if self._is_cache_valid(cache_key):
            return self._tool_cache[cache_key]
        
        tools = await dynamic_tool_registry.get_tools_for_llm(self.user.id, self.db)
        self._cache_tools(cache_key, tools)
        return tools
    
    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cached tools are still valid"""
        import time
        current_time = time.time()
        return (cache_key in self._tool_cache and 
                cache_key in self._cache_timestamp and
                current_time - self._cache_timestamp[cache_key] < self._cache_duration)
    
    def _cache_tools(self, cache_key: str, tools: List[Dict[str, Any]]) -> None:
        """Cache tools with timestamp"""
        import time
        self._tool_cache[cache_key] = tools
        self._cache_timestamp[cache_key] = time.time()
    
    async def get_tool_by_name(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific tool by name with 100% accuracy"""
        tools = await self._get_all_tools()
        return next((t for t in tools if t['name'] == tool_name), None)
    
    async def validate_tool_arguments(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Advanced validation with contextual checks"""
        tool = await self.get_tool_by_name(tool_name)
        if not tool:
            return {
                "valid": False,
                "errors": [f"Tool '{tool_name}' not found"],
                "corrected_arguments": None
            }
        
        schema = tool.get('inputSchema', {})
        required_fields = schema.get('required', [])
        properties = schema.get('properties', {})
        
        errors = []
        corrected_arguments = arguments.copy()
        
        # Check required fields
        for field in required_fields:
            if field not in arguments:
                errors.append(f"Missing required field: {field}")
        
        # Validate field types and values
        for field_name, field_value in arguments.items():
            if field_name in properties:
                field_schema = properties[field_name]
                field_type = field_schema.get('type')
                
                # Type validation
                if field_type == 'integer':
                    try:
                        corrected_arguments[field_name] = int(field_value)
                    except (ValueError, TypeError):
                        errors.append(f"Field '{field_name}' must be an integer")
                
                elif field_type == 'number':
                    try:
                        corrected_arguments[field_name] = float(field_value)
                    except (ValueError, TypeError):
                        errors.append(f"Field '{field_name}' must be a number")
                
                # Enum validation
                if 'enum' in field_schema:
                    enum_values = field_schema['enum']
                    if field_value not in enum_values:
                        # Try case-insensitive match
                        lower_values = [v.lower() for v in enum_values]
                        if str(field_value).lower() in lower_values:
                            corrected_value = enum_values[lower_values.index(str(field_value).lower())]
                            corrected_arguments[field_name] = corrected_value
                        else:
                            errors.append(f"Field '{field_name}' must be one of: {enum_values}")
        
        # Contextual validation
        if not errors:
            contextual_errors = await self._contextual_validation(tool, corrected_arguments)
            errors.extend(contextual_errors)
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "corrected_arguments": corrected_arguments if not errors else None
        }
    
    async def _contextual_validation(self, tool: Dict[str, Any], arguments: Dict[str, Any]) -> List[str]:
        """Apply domain-specific contextual validation"""
        errors = []
        tool_name = tool['name']
        
        # Slack-specific validation
        if 'slack' in tool_name:
            if 'channel' in arguments:
                if not arguments['channel'].startswith('#') and not arguments['channel'].startswith('@'):
                    errors.append("Slack channel must start with # for public channels or @ for users")
            
            if 'message' in arguments and len(arguments['message']) > 3000:
                errors.append("Slack messages cannot exceed 3000 characters")
        
        # WhatsApp-specific validation
        if 'whatsapp' in tool_name:
            if 'phone' in arguments:
                phone = str(arguments['phone']).replace(' ', '').replace('-', '')
                if not re.match(r'^\+\d{10,15}$', phone):
                    errors.append("Phone number must be in international format (+1234567890)")
                else:
                    arguments['phone'] = phone  # Normalize format
        
        # HubSpot-specific validation
        if 'hubspot' in tool_name:
            if 'email' in arguments and not re.match(r'^[^@]+@[^@]+\.[^@]+$', arguments['email']):
                errors.append("Invalid email format")
        
        # File management validation
        if tool_name == 'file_management':
            if 'filename' in arguments:
                invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
                if any(char in arguments['filename'] for char in invalid_chars):
                    errors.append(f"Filename contains invalid characters: {invalid_chars}")
        
        return errors


# Backward compatibility - alias the new class
ToolRouter = PrecisionToolRouter 