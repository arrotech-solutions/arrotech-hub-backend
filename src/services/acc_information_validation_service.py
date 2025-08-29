"""
ACC Information Validation Service

Service to validate the completeness and quality of ACC issue information
and suggest improvements for better issue tracking and resolution.
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class ACCInformationValidationService:
    """Service to validate ACC issue information completeness and quality."""
    
    def __init__(self):
        self.required_fields = ['title', 'description', 'status', 'assignedTo', 'assignedToType', 'dueDate']
        self.recommended_fields = ['issueSubtypeId', 'priority']
        self.minimum_description_length = 20
        self.minimum_title_length = 5
        
    async def validate_issue_completeness(self, issue_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate if an issue has complete and quality information.
        
        Returns:
        {
            'is_complete': bool,
            'completeness_score': float,
            'missing_fields': List[str],
            'suggestions': List[str],
            'quality_issues': List[str]
        }
        """
        try:
            logger.info(f"Validating issue completeness for issue {issue_data.get('id', 'unknown')}")
            
            # ACC issues have fields at the top level, not under 'attributes'
            # But also check 'attributes' as fallback for different response formats
            if 'attributes' in issue_data and issue_data['attributes']:
                # Some APIs might nest under attributes
                attributes = issue_data['attributes']
                logger.info("[VALIDATION DEBUG] Using nested attributes structure")
            else:
                # ACC Issues API has fields at top level
                attributes = issue_data
                logger.info("[VALIDATION DEBUG] Using top-level field structure")
            
            validation_result = {
                'is_complete': True,
                'completeness_score': 0.0,
                'missing_fields': [],
                'suggestions': [],
                'quality_issues': []
            }
            
            logger.info(f"[VALIDATION DEBUG] Checking fields in data: {list(attributes.keys())}")
            
            # 1. Check required fields
            self._check_required_fields(attributes, validation_result)
            
            # 2. Check recommended fields
            self._check_recommended_fields(attributes, validation_result)
            
            # 3. Check content quality
            self._check_content_quality(attributes, validation_result)
            
            # 4. Check for completeness indicators
            self._check_completeness_indicators(attributes, validation_result)
            
            # 5. Calculate overall completeness score
            self._calculate_completeness_score(validation_result)
            
            # 6. Determine if issue is complete
            validation_result['is_complete'] = (
                len(validation_result['missing_fields']) == 0 and
                validation_result['completeness_score'] >= 0.7
            )
            
            # 7. Generate improvement suggestions
            self._generate_suggestions(validation_result)
            
            logger.info(
                f"Issue validation complete - Score: {validation_result['completeness_score']:.2f}, "
                f"Complete: {validation_result['is_complete']}"
            )
            
            return validation_result
            
        except Exception as e:
            import traceback
            logger.error(f"[VALIDATION ERROR] ===== VALIDATION CRASHED =====")
            logger.error(f"[VALIDATION ERROR] Exception: {e}")
            logger.error(f"[VALIDATION ERROR] Traceback: {traceback.format_exc()}")
            logger.error(f"[VALIDATION ERROR] Issue data that caused crash: {issue_data}")
            logger.error(f"[VALIDATION ERROR] ================================")
            
            # Instead of returning validation_error, return empty missing fields so we can see actual data
            return {
                'is_complete': False,
                'completeness_score': 0.0,
                'missing_fields': [],  # Don't mask the real missing fields with "validation_error"
                'suggestions': [f'Validation service temporarily unavailable. Error: {str(e)}'],
                'quality_issues': []
            }
    
    def _check_required_fields(self, attributes: Dict[str, Any], result: Dict[str, Any]):
        """Check if required fields are present and valid."""
        for field in self.required_fields:
            # Safe extraction and strip (handle None values)
            raw_value = attributes.get(field, '')
            if raw_value is None:
                value = ''
            else:
                value = str(raw_value).strip()
            
            if not value:
                result['missing_fields'].append(field)
                result['quality_issues'].append(f'Missing required field: {field}')
            elif field == 'title' and len(value) < self.minimum_title_length:
                result['quality_issues'].append(
                    f'Title too short (minimum {self.minimum_title_length} characters)'
                )
            elif field == 'description' and len(value) < self.minimum_description_length:
                result['quality_issues'].append(
                    f'Description too brief (minimum {self.minimum_description_length} characters)'
                )
    
    def _check_recommended_fields(self, attributes: Dict[str, Any], result: Dict[str, Any]):
        """Check if recommended fields are present."""
        logger.info(f"[VALIDATION DEBUG] Checking recommended fields: {self.recommended_fields}")
        
        # Initialize recommended_missing if not exists
        if 'recommended_missing' not in result:
            result['recommended_missing'] = []
        
        for field in self.recommended_fields:
            value = attributes.get(field)
            logger.info(f"[VALIDATION DEBUG] Field '{field}': value = {value} (type: {type(value)})")
            
            # Check if field is missing or empty (safe .strip() check)
            is_missing = (
                value is None or 
                value == '' or 
                (isinstance(value, str) and value.strip() == '')
            )
            
            if is_missing:
                logger.warning(f"[VALIDATION DEBUG] Recommended field '{field}' is missing")
                result['recommended_missing'].append(field)
            else:
                logger.info(f"[VALIDATION DEBUG] Recommended field '{field}' is present and valid")
    
    def _check_content_quality(self, attributes: Dict[str, Any], result: Dict[str, Any]):
        """Check the quality of content in title and description."""
        # Safe extraction and strip (handle None values)
        raw_title = attributes.get('title', '')
        raw_description = attributes.get('description', '')
        
        title = '' if raw_title is None else str(raw_title).strip()
        description = '' if raw_description is None else str(raw_description).strip()
        
        # Check title quality
        if title:
            if len(title.split()) < 3:
                result['quality_issues'].append('Title should be more descriptive (use more words)')
            
            if title.isupper():
                result['quality_issues'].append('Title should not be in all caps')
            
            if not re.search(r'[.!?]$', title) and len(title) > 50:
                result['quality_issues'].append('Long title should end with punctuation')
        
        # Check description quality
        if description:
            word_count = len(description.split())
            if word_count < 10:
                result['quality_issues'].append('Description should be more detailed (more words)')
            
            if not re.search(r'[.!?]', description):
                result['quality_issues'].append('Description should include proper punctuation')
            
            # Check for common incomplete patterns
            incomplete_patterns = [
                r'\btbd\b', r'\btodo\b', r'\bfix\b$', r'\btest\b$',
                r'\bupdate\b$', r'\bcheck\b$', r'\bSee\s+attachment',
                r'\bAs\s+discussed\b', r'\bMore\s+info\s+needed\b'
            ]
            
            for pattern in incomplete_patterns:
                if re.search(pattern, description, re.IGNORECASE):
                    result['quality_issues'].append(
                        'Description appears incomplete or placeholder text'
                    )
                    break
    
    def _check_completeness_indicators(self, attributes: Dict[str, Any], result: Dict[str, Any]):
        """Check for specific indicators that suggest completeness."""
        title = attributes.get('title', '').lower()
        description = attributes.get('description', '').lower()
        
        # Positive indicators
        positive_indicators = [
            ('location mentioned', r'\b(room|floor|building|area|zone|sector)\s+\w+'),
            ('specific measurements', r'\b\d+\s*(mm|cm|m|ft|in|inches|feet|meters)'),
            ('date/time mentioned', r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}:\d{2})'),
            ('equipment mentioned', r'\b(equipment|machine|tool|device|system)\b'),
            ('responsible party', r'\b(contractor|vendor|team|department|manager)\b')
        ]
        
        completeness_indicators = []
        for indicator_name, pattern in positive_indicators:
            if re.search(pattern, title + ' ' + description, re.IGNORECASE):
                completeness_indicators.append(indicator_name)
        
        # Store indicators for scoring
        result['completeness_indicators'] = completeness_indicators
        
        # Negative indicators (suggest incompleteness)
        negative_indicators = [
            r'\bunknown\b', r'\btbd\b', r'\btbr\b', r'\bpending\b',
            r'\bneeds?\s+review\b', r'\bneeds?\s+input\b', r'\bto\s+be\s+determined\b'
        ]
        
        for pattern in negative_indicators:
            if re.search(pattern, title + ' ' + description, re.IGNORECASE):
                result['quality_issues'].append('Contains placeholder or uncertain language')
                break
    
    def _calculate_completeness_score(self, result: Dict[str, Any]):
        """Calculate an overall completeness score."""
        score = 1.0
        
        # Deduct for missing required fields (major impact)
        required_missing = len([f for f in result['missing_fields'] if f in self.required_fields])
        score -= required_missing * 0.3
        
        # Deduct for missing recommended fields (minor impact)
        recommended_missing = len([f for f in result['missing_fields'] if f in self.recommended_fields])
        score -= recommended_missing * 0.1
        
        # Deduct for quality issues
        score -= len(result['quality_issues']) * 0.05
        
        # Add bonus for completeness indicators
        indicators = result.get('completeness_indicators', [])
        score += len(indicators) * 0.02
        
        # Ensure score is between 0 and 1
        result['completeness_score'] = max(0.0, min(1.0, score))
    
    def _generate_suggestions(self, result: Dict[str, Any]):
        """Generate improvement suggestions based on validation results."""
        suggestions = []
        
        # Suggestions for missing fields
        missing_fields = result['missing_fields']
        
        if 'title' in missing_fields:
            suggestions.append('Add a clear, descriptive title that summarizes the issue')
        
        if 'description' in missing_fields:
            suggestions.append('Provide a detailed description of the problem, including location and impact')
        
        if 'issueSubtypeId' in missing_fields:
            suggestions.append('Select an appropriate issue type/category for better tracking')
        
        if 'priority' in missing_fields:
            suggestions.append('Set a priority level to help with resource allocation')
        
        if 'assignedTo' in missing_fields:
            suggestions.append('Assign the issue to a responsible person or team')
        
        if 'dueDate' in missing_fields:
            suggestions.append('Set a target resolution date for better project planning')
        
        # Suggestions for quality issues
        quality_issues = result['quality_issues']
        
        if any('title' in issue.lower() for issue in quality_issues):
            suggestions.append('Improve the title: make it more descriptive and specific')
        
        if any('description' in issue.lower() for issue in quality_issues):
            suggestions.append('Enhance the description: add more context, location details, and specific steps to reproduce')
        
        if any('incomplete' in issue.lower() or 'placeholder' in issue.lower() for issue in quality_issues):
            suggestions.append('Replace placeholder text with specific, actionable information')
        
        # General improvement suggestions
        if result['completeness_score'] < 0.5:
            suggestions.append('This issue needs significant improvement to be actionable')
        elif result['completeness_score'] < 0.7:
            suggestions.append('Consider adding more detail to help with faster resolution')
        
        # Add location-specific suggestions
        if not any('location' in indicator for indicator in result.get('completeness_indicators', [])):
            suggestions.append('Include specific location information (room, floor, building, etc.)')
        
        # Add context suggestions
        if result['completeness_score'] < 0.8:
            suggestions.extend([
                'Consider adding photos or attachments if applicable',
                'Include steps to reproduce the issue if it\'s a recurring problem',
                'Mention any safety concerns or business impact',
                'Reference related issues or previous occurrences if any'
            ])
        
        result['suggestions'] = suggestions
    
    def get_field_suggestions(self, field_name: str) -> List[str]:
        """Get specific suggestions for improving a particular field."""
        suggestions_map = {
            'title': [
                'Use specific, descriptive language',
                'Include the location or area affected',
                'Mention the type of problem (structural, electrical, etc.)',
                'Keep it concise but informative'
            ],
            'description': [
                'Describe what happened, when, and where',
                'Include the impact on work or safety',
                'Mention any temporary workarounds',
                'List steps already taken to address the issue',
                'Include relevant measurements or specifications'
            ],
            'priority': [
                'Consider safety implications',
                'Evaluate impact on project timeline',
                'Assess cost implications',
                'Consider regulatory or compliance requirements'
            ],
            'assignedTo': [
                'Assign to the most appropriate team or person',
                'Consider expertise required for resolution',
                'Ensure assignee has authority to make decisions',
                'Include contact information if not in system'
            ]
        }
        
        return suggestions_map.get(field_name, [])


# Global instance
info_validation_service = ACCInformationValidationService()
