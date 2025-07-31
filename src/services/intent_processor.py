"""
Intent Processor Service for classifying user intent and determining tool requirements.
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import IntentClassifier, User

logger = logging.getLogger(__name__)


class IntentProcessor:
    """Process and classify user intent to determine appropriate actions."""
    
    def __init__(self, user: User, db: AsyncSession):
        self.user = user
        self.db = db
    
    async def classify_intent(self, user_input: str) -> IntentClassifier:
        """
        Classify user intent and determine if tools are required.
        
        Args:
            user_input: The user's message
            
        Returns:
            IntentClassifier with classification results
        """
        # Simple rule-based classification for now
        # In the future, this could use an LLM for more sophisticated classification
        
        user_input_lower = user_input.lower().strip()
        
        # Define intent patterns
        intent_patterns = {
            'chat': [
                'hi', 'hello', 'hey', 'good morning', 'good afternoon', 'good evening',
                'how are you', 'what\'s up', 'thanks', 'thank you', 'bye', 'goodbye'
            ],
            'action': [
                'send', 'create', 'generate', 'download', 'upload', 'execute', 'run',
                'call', 'manage', 'update', 'delete', 'scrape', 'extract', 'build'
            ],
            'query': [
                'get', 'find', 'search', 'list', 'show', 'display', 'retrieve',
                'what is', 'how many', 'when', 'where', 'who', 'which'
            ],
            'analysis': [
                'analyze', 'analyze', 'report', 'dashboard', 'metrics', 'statistics',
                'trends', 'performance', 'insights', 'data', 'chart', 'graph'
            ],
            'automation': [
                'automate', 'workflow', 'schedule', 'trigger', 'pipeline', 'integration',
                'sync', 'connect', 'link', 'bridge', 'orchestrate'
            ]
        }
        
        # Calculate confidence scores for each intent
        intent_scores = {}
        for intent_type, patterns in intent_patterns.items():
            score = 0
            for pattern in patterns:
                if pattern in user_input_lower:
                    score += 1
            
            # Normalize score by pattern length
            if patterns:
                intent_scores[intent_type] = score / len(patterns)
            else:
                intent_scores[intent_type] = 0
        
        # Determine primary intent
        primary_intent = max(intent_scores.items(), key=lambda x: x[1])
        intent_type = primary_intent[0]
        confidence = primary_intent[1]
        
        # Determine if tools are required
        requires_tools = intent_type in ['action', 'query', 'analysis', 'automation']
        
        # Generate explanation
        explanation = self._generate_explanation(intent_type, user_input, confidence)
        
        # Suggest tools based on intent
        suggested_tools = self._suggest_tools(intent_type, user_input)
        
        return IntentClassifier(
            intent_type=intent_type,
            confidence=confidence,
            requires_tools=requires_tools,
            suggested_tools=suggested_tools,
            explanation=explanation
        )
    
    def _generate_explanation(self, intent_type: str, user_input: str, confidence: float) -> str:
        """Generate explanation for the intent classification."""
        explanations = {
            'chat': f"Detected conversational intent with {confidence:.1%} confidence. This appears to be a general chat message.",
            'action': f"Detected action intent with {confidence:.1%} confidence. User wants to perform a specific action.",
            'query': f"Detected query intent with {confidence:.1%} confidence. User is requesting information or data.",
            'analysis': f"Detected analysis intent with {confidence:.1%} confidence. User wants analytical insights or reports.",
            'automation': f"Detected automation intent with {confidence:.1%} confidence. User wants to set up automated workflows."
        }
        
        return explanations.get(intent_type, f"Detected {intent_type} intent with {confidence:.1%} confidence.")
    
    def _suggest_tools(self, intent_type: str, user_input: str) -> List[str]:
        """Suggest relevant tools based on intent type."""
        tool_suggestions = {
            'chat': [],
            'action': [
                'slack_team_communication',
                'file_management',
                'web_tools',
                'content_creation'
            ],
            'query': [
                'ga4_get_traffic',
                'ga4_get_conversions',
                'hubspot_crm_management',
                'web_tools'
            ],
            'analysis': [
                'ga4_get_traffic',
                'ga4_get_conversions',
                'hubspot_crm_management',
                'predictive_analytics_engine'
            ],
            'automation': [
                'workflow_builder',
                'marketing_campaign_automation',
                'api_management'
            ]
        }
        
        return tool_suggestions.get(intent_type, [])
    
    async def should_use_tools(self, user_input: str) -> bool:
        """
        Quick check to determine if tools should be used.
        
        Args:
            user_input: The user's message
            
        Returns:
            True if tools should be used, False otherwise
        """
        # Simple keyword-based check for performance
        command_words = [
            'send', 'create', 'get', 'list', 'find', 'scrape', 'generate',
            'download', 'upload', 'execute', 'run', 'call', 'manage', 'analyze',
            'report', 'automate', 'workflow', 'sync', 'connect'
        ]
        
        user_input_lower = user_input.lower()
        return any(word in user_input_lower for word in command_words)
    
    async def get_intent_confidence(self, user_input: str) -> float:
        """
        Get confidence score for tool usage.
        
        Args:
            user_input: The user's message
            
        Returns:
            Confidence score between 0 and 1
        """
        intent_classifier = await self.classify_intent(user_input)
        return intent_classifier.confidence
    
    async def explain_intent(self, user_input: str) -> Dict[str, Any]:
        """
        Provide detailed explanation of intent classification.
        
        Args:
            user_input: The user's message
            
        Returns:
            Detailed explanation with confidence scores
        """
        intent_classifier = await self.classify_intent(user_input)
        
        return {
            "user_input": user_input,
            "intent_type": intent_classifier.intent_type,
            "confidence": intent_classifier.confidence,
            "requires_tools": intent_classifier.requires_tools,
            "suggested_tools": intent_classifier.suggested_tools,
            "explanation": intent_classifier.explanation,
            "recommendation": self._get_recommendation(intent_classifier)
        }
    
    def _get_recommendation(self, intent_classifier: IntentClassifier) -> str:
        """Get recommendation based on intent classification."""
        if intent_classifier.intent_type == 'chat':
            return "Generate a conversational response without tools."
        elif intent_classifier.confidence > 0.7:
            return f"High confidence ({intent_classifier.confidence:.1%}) - proceed with tool execution."
        elif intent_classifier.confidence > 0.4:
            return f"Medium confidence ({intent_classifier.confidence:.1%}) - use tools with caution."
        else:
            return f"Low confidence ({intent_classifier.confidence:.1%}) - consider asking for clarification." 