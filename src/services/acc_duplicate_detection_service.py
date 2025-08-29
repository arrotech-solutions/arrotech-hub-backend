"""
ACC Duplicate Detection Service

AI-powered service to detect potential duplicate issues in ACC projects
using semantic similarity and rule-based matching.
"""

import logging
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy.ext.asyncio import AsyncSession

from .acc_service import acc_service
from .llm_service import LLMService

logger = logging.getLogger(__name__)


class ACCDuplicateDetectionService:
    """Service to detect potential duplicate issues in ACC projects."""
    
    def __init__(self):
        self.llm_service = LLMService()
        self.similarity_threshold = 0.60  # Threshold for considering issues similar (lowered to catch more)
        self.confidence_threshold = 0.65   # Threshold for high confidence duplicates (lowered to catch more)
        
    async def check_for_duplicates(
        self, 
        connection: Any, 
        project_id: str, 
        new_issue: Dict[str, Any],
        user_id: int,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Check if a new issue is a potential duplicate of existing issues.
        
        Returns:
        {
            'is_duplicate': bool,
            'confidence': float,
            'similarity_score': float,
            'similar_issues': List[Dict],
            'reasoning': str
        }
        """
        try:
            issue_id = new_issue.get('id', 'unknown')
            issue_title = new_issue.get('title', 'Unknown Issue')
            
            logger.info(f"[DUPLICATE DEBUG] ===== CHECKING FOR DUPLICATES =====")
            logger.info(f"[DUPLICATE DEBUG] Issue ID: {issue_id}")
            logger.info(f"[DUPLICATE DEBUG] Issue Title: {issue_title}")
            logger.info(f"[DUPLICATE DEBUG] Project ID: {project_id}")
            logger.info(f"[DUPLICATE DEBUG] Similarity threshold: {self.similarity_threshold}")
            logger.info(f"[DUPLICATE DEBUG] Confidence threshold: {self.confidence_threshold}")
            
            # Get all existing issues in the project
            existing_issues = await self._get_existing_issues(connection, project_id, user_id, db)
            logger.info(f"[DUPLICATE DEBUG] Found {len(existing_issues)} existing issues to compare against")
            
            if not existing_issues:
                return {
                    'is_duplicate': False,
                    'confidence': 0.0,
                    'similarity_score': 0.0,
                    'similar_issues': [],
                    'reasoning': 'No existing issues to compare against (project may be extremely busy or empty)'
                }
            
            # Extract issue content for comparison
            new_issue_content = self._extract_issue_content(new_issue)
            logger.info(f"[DUPLICATE DEBUG] New issue content extracted: '{new_issue_content[:100]}{'...' if len(new_issue_content) > 100 else ''}'")
            
            if not new_issue_content.strip():
                logger.warning(f"[DUPLICATE DEBUG] ❌ NEW ISSUE HAS NO CONTENT TO ANALYZE!")
                logger.warning(f"[DUPLICATE DEBUG] Issue data keys: {list(new_issue.keys())}")
                logger.warning(f"[DUPLICATE DEBUG] Issue data: {new_issue}")
                return {
                    'is_duplicate': False,
                    'confidence': 0.0,
                    'similarity_score': 0.0,
                    'similar_issues': [],
                    'reasoning': 'New issue has no content to analyze'
                }
            
            # Find similar issues using multiple methods
            similar_issues = []
            
            # 1. Semantic similarity using TF-IDF and cosine similarity
            semantic_results = await self._find_semantic_similarities(
                new_issue_content, existing_issues
            )
            similar_issues.extend(semantic_results)
            
            # 2. Rule-based similarity (title matching, keywords, etc.)
            rule_based_results = await self._find_rule_based_similarities(
                new_issue, existing_issues
            )
            similar_issues.extend(rule_based_results)
            
            # 3. AI-powered similarity using LLM
            ai_results = await self._find_ai_similarities(
                new_issue, existing_issues[:5]  # Limit to top 5 for AI analysis
            )
            similar_issues.extend(ai_results)
            
            # Combine and rank results
            combined_results = self._combine_similarity_results(similar_issues)
            
            if not combined_results:
                return {
                    'is_duplicate': False,
                    'confidence': 0.0,
                    'similarity_score': 0.0,
                    'similar_issues': [],
                    'reasoning': 'No similar issues found'
                }
            
            # Get best match
            best_match = combined_results[0]
            max_similarity = best_match['similarity_score']
            confidence = best_match['confidence']
            
            # Determine if it's a duplicate
            is_duplicate = (
                max_similarity >= self.similarity_threshold and 
                confidence >= self.confidence_threshold
            )
            
            # Generate reasoning
            reasoning = self._generate_reasoning(
                new_issue, best_match, max_similarity, confidence, is_duplicate
            )
            
            logger.info(f"[DUPLICATE DEBUG] ===== DUPLICATE DETECTION RESULT =====")
            logger.info(f"[DUPLICATE DEBUG] Is duplicate: {is_duplicate}")
            logger.info(f"[DUPLICATE DEBUG] Max similarity: {max_similarity:.1%}")
            logger.info(f"[DUPLICATE DEBUG] Confidence: {confidence:.1%}")
            logger.info(f"[DUPLICATE DEBUG] Similar issues found: {len(combined_results)}")
            if combined_results:
                logger.info(f"[DUPLICATE DEBUG] Best match: {best_match.get('issue', {}).get('title', 'Unknown')}")
            logger.info(f"[DUPLICATE DEBUG] ============================================")
            
            return {
                'is_duplicate': is_duplicate,
                'confidence': confidence,
                'similarity_score': max_similarity,
                'similar_issues': combined_results[:3],  # Return top 3 similar issues
                'reasoning': reasoning
            }
            
        except Exception as e:
            logger.error(f"Error checking for duplicates: {e}")
            return {
                'is_duplicate': False,
                'confidence': 0.0,
                'similarity_score': 0.0,
                'similar_issues': [],
                'reasoning': f'Error during duplicate detection: {str(e)}'
            }
    
    async def _get_existing_issues(self, connection: Any, project_id: str, user_id: int, db: AsyncSession) -> List[Dict]:
        """Get all existing issues in a project using tool executor pattern for consistency."""
        try:
            # Use tool executor pattern to avoid buffer overflow issues
            from sqlalchemy import select
            from sqlalchemy.ext.asyncio import AsyncSession

            from ..models import User
            from .tool_executor import tool_executor

            # Get user for tool executor
            user_query = select(User).where(User.id == user_id)
            result = await db.execute(user_query)
            user = result.scalars().first()
            
            if not user:
                logger.error(f"User {user_id} not found for duplicate detection")
                return []
                
            # Execute through tool executor (same pattern as direct tool calls)
            issues_result = await tool_executor.execute_tool(
                tool_name="acc_get_issues",
                arguments={"project_id": project_id},
                user=user,
                db=db
            )
            
            if not issues_result.get('success', False):
                logger.warning(f"Failed to get issues for duplicate detection: {issues_result}")
                return []
            
            # Check if this is a fallback response due to extremely busy project
            result_data = issues_result.get('result', {})
            if isinstance(result_data, dict) and result_data.get('fallback_used', False):
                logger.info(f"Project extremely busy - duplicate detection skipped for performance")
                return []  # Skip duplicate detection for extremely busy projects
            
            # Extract issues data from tool executor result
            issues_data = issues_result.get('result', {})
            
            # Parse issues data from response
            if isinstance(issues_data, dict) and 'content' in issues_data:
                # Extract from MCP response format
                content = issues_data['content']
                if isinstance(content, list) and content:
                    content_text = content[0].get('text', '{}')
                    try:
                        import json
                        parsed_data = json.loads(content_text)
                        return parsed_data.get('data', [])
                    except json.JSONDecodeError:
                        return []
                return []
            elif isinstance(issues_data, dict) and 'data' in issues_data:
                return issues_data['data']
            elif isinstance(issues_data, list):
                return issues_data
            
            return []
            
        except Exception as e:
            logger.error(f"Error getting existing issues for duplicate detection: {e}")
            return []
    
    def _extract_issue_content(self, issue: Dict[str, Any]) -> str:
        """Extract searchable content from an issue."""
        try:
            # Handle both webhook format (direct) and API format (nested under attributes)
            if 'attributes' in issue and issue['attributes']:
                # API format: nested under attributes
                attributes = issue['attributes']
                title = attributes.get('title', '')
                description = attributes.get('description', '')
            else:
                # Webhook format: direct access
                title = issue.get('title', '')
                description = issue.get('description', '')
            
            logger.info(f"[CONTENT EXTRACT DEBUG] Issue ID: {issue.get('id', 'unknown')}")
            logger.info(f"[CONTENT EXTRACT DEBUG] Extracted title: '{title}'")
            logger.info(f"[CONTENT EXTRACT DEBUG] Extracted description: '{description}'")
            
            # Combine title and description with weight on title
            content = f"{title} {title} {description}".strip()  # Title twice for emphasis
            
            logger.info(f"[CONTENT EXTRACT DEBUG] Final content: '{content[:100]}{'...' if len(content) > 100 else ''}'")
            
            return content
            
        except Exception as e:
            logger.error(f"Error extracting issue content: {e}")
            return ""
    
    async def _find_semantic_similarities(
        self, 
        new_content: str, 
        existing_issues: List[Dict]
    ) -> List[Dict]:
        """Find semantic similarities using TF-IDF vectorization."""
        try:
            if not existing_issues:
                return []
            
            # Extract content from existing issues
            existing_contents = [
                self._extract_issue_content(issue) for issue in existing_issues
            ]
            
            # Filter out empty contents
            valid_pairs = [
                (content, issue) for content, issue in zip(existing_contents, existing_issues)
                if content.strip()
            ]
            
            if not valid_pairs:
                return []
            
            valid_contents, valid_issues = zip(*valid_pairs)
            all_contents = [new_content] + list(valid_contents)
            
            # Create TF-IDF vectors
            vectorizer = TfidfVectorizer(
                stop_words='english',
                max_features=1000,
                ngram_range=(1, 2)
            )
            
            tfidf_matrix = vectorizer.fit_transform(all_contents)
            
            # Compute cosine similarity
            similarities = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:]).flatten()
            
            # Create results
            results = []
            for i, similarity in enumerate(similarities):
                if similarity > 0.3:  # Only include reasonably similar issues
                    results.append({
                        'issue': valid_issues[i],
                        'similarity_score': float(similarity),
                        'confidence': float(similarity * 0.9),  # Slightly lower confidence for semantic
                        'method': 'semantic_tfidf',
                        'reasoning': f'Semantic similarity: {similarity:.2f}'
                    })
            
            return results
            
        except Exception as e:
            logger.error(f"Error in semantic similarity: {e}")
            return []
    
    async def _find_rule_based_similarities(
        self, 
        new_issue: Dict[str, Any], 
        existing_issues: List[Dict]
    ) -> List[Dict]:
        """Find similarities using rule-based matching."""
        try:
            results = []
            
            # Handle both webhook format (direct) and API format (nested under attributes)
            if 'attributes' in new_issue and new_issue['attributes']:
                new_title = new_issue['attributes'].get('title', '').lower()
                new_desc = new_issue['attributes'].get('description', '').lower()
            else:
                new_title = new_issue.get('title', '').lower()
                new_desc = new_issue.get('description', '').lower()
            
            logger.info(f"[RULE DEBUG] New issue title: '{new_title}'")
            logger.info(f"[RULE DEBUG] New issue description: '{new_desc[:50]}{'...' if len(new_desc) > 50 else ''}'")
            
            for existing_issue in existing_issues:
                # Handle both formats for existing issues too
                if 'attributes' in existing_issue and existing_issue['attributes']:
                    existing_title = existing_issue['attributes'].get('title', '').lower()
                    existing_desc = existing_issue['attributes'].get('description', '').lower()
                else:
                    existing_title = existing_issue.get('title', '').lower()
                    existing_desc = existing_issue.get('description', '').lower()
                
                similarity_score = 0.0
                reasoning_parts = []
                
                # 1. Title similarity (weighted heavily)
                title_similarity = SequenceMatcher(None, new_title, existing_title).ratio()
                if title_similarity > 0.5:
                    similarity_score += title_similarity * 0.6
                    reasoning_parts.append(f"Title similarity: {title_similarity:.2f}")
                
                # 2. Description similarity
                if new_desc and existing_desc:
                    desc_similarity = SequenceMatcher(None, new_desc, existing_desc).ratio()
                    if desc_similarity > 0.3:
                        similarity_score += desc_similarity * 0.3
                        reasoning_parts.append(f"Description similarity: {desc_similarity:.2f}")
                
                # 3. Common keywords
                new_keywords = set(re.findall(r'\b\w{4,}\b', new_title + ' ' + new_desc))
                existing_keywords = set(re.findall(r'\b\w{4,}\b', existing_title + ' ' + existing_desc))
                
                if new_keywords and existing_keywords:
                    common_keywords = new_keywords.intersection(existing_keywords)
                    keyword_ratio = len(common_keywords) / len(new_keywords.union(existing_keywords))
                    if keyword_ratio > 0.2:
                        similarity_score += keyword_ratio * 0.1
                        reasoning_parts.append(f"Common keywords: {len(common_keywords)}")
                
                # 4. Same issue subtype
                new_subtype = new_issue.get('issueSubtypeId') or (new_issue.get('attributes', {}).get('issueSubtypeId'))
                existing_subtype = existing_issue.get('issueSubtypeId') or (existing_issue.get('attributes', {}).get('issueSubtypeId'))
                
                if new_subtype and new_subtype == existing_subtype:
                    similarity_score += 0.1
                    reasoning_parts.append("Same issue subtype")
                
                # Add to results if similar enough
                if similarity_score > 0.4:
                    results.append({
                        'issue': existing_issue,
                        'similarity_score': min(similarity_score, 1.0),
                        'confidence': min(similarity_score * 0.95, 1.0),
                        'method': 'rule_based',
                        'reasoning': '; '.join(reasoning_parts)
                    })
            
            return results
            
        except Exception as e:
            logger.error(f"Error in rule-based similarity: {e}")
            return []
    
    async def _find_ai_similarities(
        self, 
        new_issue: Dict[str, Any], 
        existing_issues: List[Dict]
    ) -> List[Dict]:
        """Find similarities using AI/LLM analysis."""
        try:
            if not existing_issues:
                return []
            
            new_content = self._extract_issue_content(new_issue)
            results = []
            
            for existing_issue in existing_issues:
                existing_content = self._extract_issue_content(existing_issue)
                
                if not existing_content.strip():
                    continue
                
                # Extract titles and descriptions handling both formats
                if 'attributes' in new_issue and new_issue['attributes']:
                    new_title = new_issue['attributes'].get('title', '')
                    new_desc = new_issue['attributes'].get('description', '')
                else:
                    new_title = new_issue.get('title', '')
                    new_desc = new_issue.get('description', '')
                
                if 'attributes' in existing_issue and existing_issue['attributes']:
                    existing_title = existing_issue['attributes'].get('title', '')
                    existing_desc = existing_issue['attributes'].get('description', '')
                else:
                    existing_title = existing_issue.get('title', '')
                    existing_desc = existing_issue.get('description', '')
                
                # Use LLM to analyze similarity
                prompt = f"""
Analyze if these two construction issues are duplicates or very similar:

NEW ISSUE:
Title: {new_title}
Description: {new_desc}

EXISTING ISSUE:
Title: {existing_title}
Description: {existing_desc}

Rate the similarity from 0.0 to 1.0 and provide reasoning.
Respond in JSON format:
{{
    "similarity_score": 0.85,
    "confidence": 0.9,
    "reasoning": "Both issues describe the same problem with steel beam delivery delays in similar locations"
}}
"""
                
                try:
                    llm_response = await self.llm_service.chat_completion([
                        {"role": "user", "content": prompt}
                    ], temperature=0.1)
                    
                    if llm_response.content:
                        import json
                        ai_result = json.loads(llm_response.content)
                        
                        similarity_score = float(ai_result.get('similarity_score', 0))
                        confidence = float(ai_result.get('confidence', 0))
                        reasoning = ai_result.get('reasoning', 'AI analysis')
                        
                        if similarity_score > 0.5:  # Only include reasonably similar
                            results.append({
                                'issue': existing_issue,
                                'similarity_score': similarity_score,
                                'confidence': confidence,
                                'method': 'ai_llm',
                                'reasoning': f'AI analysis: {reasoning}'
                            })
                            
                except Exception as llm_error:
                    logger.warning(f"LLM analysis failed: {llm_error}")
                    continue
            
            return results
            
        except Exception as e:
            logger.error(f"Error in AI similarity: {e}")
            return []
    
    def _combine_similarity_results(self, results: List[Dict]) -> List[Dict]:
        """Combine and rank similarity results from different methods."""
        try:
            if not results:
                return []
            
            # Group by issue ID
            issue_groups = {}
            for result in results:
                issue_id = result['issue'].get('id', '')
                if issue_id not in issue_groups:
                    issue_groups[issue_id] = []
                issue_groups[issue_id].append(result)
            
            # Combine results for each issue
            combined_results = []
            for issue_id, group in issue_groups.items():
                if not group:
                    continue
                
                # Take the best similarity score and average confidence
                best_similarity = max(r['similarity_score'] for r in group)
                avg_confidence = sum(r['confidence'] for r in group) / len(group)
                
                # Combine reasoning
                reasoning_parts = [r['reasoning'] for r in group]
                combined_reasoning = '; '.join(reasoning_parts)
                
                # Boost confidence if multiple methods agree
                if len(group) > 1:
                    avg_confidence = min(avg_confidence * 1.1, 1.0)
                
                combined_results.append({
                    'issue': group[0]['issue'],
                    'similarity_score': best_similarity,
                    'confidence': avg_confidence,
                    'methods_used': [r['method'] for r in group],
                    'reasoning': combined_reasoning
                })
            
            # Sort by confidence and similarity
            combined_results.sort(
                key=lambda x: (x['confidence'], x['similarity_score']), 
                reverse=True
            )
            
            return combined_results
            
        except Exception as e:
            logger.error(f"Error combining similarity results: {e}")
            return []
    
    def _generate_reasoning(
        self, 
        new_issue: Dict, 
        best_match: Dict, 
        similarity: float, 
        confidence: float, 
        is_duplicate: bool
    ) -> str:
        """Generate human-readable reasoning for the duplicate detection result."""
        try:
            reasoning_parts = []
            
            if is_duplicate:
                reasoning_parts.append(f"HIGH PROBABILITY DUPLICATE (confidence: {confidence:.1%})")
            else:
                reasoning_parts.append(f"Not a duplicate (confidence: {confidence:.1%})")
            
            reasoning_parts.append(f"Similarity score: {similarity:.1%}")
            
            if 'methods_used' in best_match:
                methods = ', '.join(best_match['methods_used'])
                reasoning_parts.append(f"Analysis methods: {methods}")
            
            if best_match.get('reasoning'):
                reasoning_parts.append(f"Details: {best_match['reasoning']}")
            
            return '. '.join(reasoning_parts)
            
        except Exception as e:
            logger.error(f"Error generating reasoning: {e}")
            return f"Analysis completed with similarity score: {similarity:.1%}"


# Global instance
duplicate_detection_service = ACCDuplicateDetectionService()
