import logging
from typing import Any, Dict, List, Optional
from .zoho_service import ZohoService
from .llm_service import llm_service

logger = logging.getLogger(__name__)

class KBAutopilotService:
    """Service for AI-powered Knowledge Base automation for Zoho Desk."""

    def __init__(self, zoho_service: ZohoService):
        self.zoho = zoho_service

    async def draft_article_from_ticket(self, ticket_id: str) -> Dict[str, Any]:
        """
        Analyzes a ticket and its resolution to draft a Knowledge Base article.
        """
        # 1. Fetch ticket details
        ticket_res = await self.zoho._desk_request("GET", f"/desk/api/v1/tickets/{ticket_id}")
        if not ticket_res or "id" not in ticket_res:
            return {"success": False, "error": f"Ticket {ticket_id} not found."}

        # 2. Fetch conversation (replies/threads)
        threads_res = await self.zoho._desk_request("GET", f"/desk/api/v1/tickets/{ticket_id}/threads")
        threads = threads_res.get("data", [])

        # 3. Construct context for LLM
        context = f"Subject: {ticket_res.get('subject')}\n"
        context += f"Description: {ticket_res.get('description')}\n\n"
        context += "Conversation History:\n"
        
        for t in threads:
            sender = t.get("from")
            content = t.get("content", "")
            # Clean HTML if necessary (simplified for now)
            context += f"- From {sender}: {content[:500]}...\n"

        # 4. Generate Draft with LLM
        prompt = f"""
        You are a Knowledge Management Expert. Convert the following customer support ticket and its resolution into a professional Knowledge Base Article.
        
        TICKET CONTEXT:
        {context}
        
        OUTPUT FORMAT (JSON):
        {{
            "title": "Clear, concise article title",
            "summary": "1-sentence summary for search snippets",
            "content": "Professional, step-by-step article content (HTML format)",
            "tags": ["tag1", "tag2"],
            "category_name": "Suggested category"
        }}
        """
        
        llm_res = await llm_service.chat_completion(
            messages=[{"role": "system", "content": prompt}],
            temperature=0.3
        )
        
        try:
            import json
            content = llm_res.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            draft = json.loads(content)
            return {"success": True, "draft": draft}
        except Exception as e:
            logger.error(f"Failed to parse LLM draft: {e}")
            return {"success": False, "error": "AI failed to generate a valid JSON draft."}

    async def auto_resolve_ticket(self, ticket_id: str) -> Dict[str, Any]:
        """
        Attempts to autonomously resolve a customer ticket by searching the Knowledge Base.
        """
        # 1. Fetch ticket details
        ticket_res = await self.zoho._desk_request("GET", f"/desk/api/v1/tickets/{ticket_id}")
        
        # If it returned an error dictionary from _desk_request
        if isinstance(ticket_res, dict) and ticket_res.get("success") is False:
            return ticket_res  # Bubble up the actual Zoho error
            
        if not ticket_res or "id" not in ticket_res:
            return {"success": False, "error": f"Ticket {ticket_id} not found or malformed response: {ticket_res}"}

        subject = ticket_res.get("subject", "")
        description = ticket_res.get("description", "")

        # 2. Search KB articles based on the ticket subject
        search_res = await self.zoho.search_articles(subject)
        
        if isinstance(search_res, dict) and search_res.get("success") is False:
            # Search API failed — log and try fallback
            logger.warning(f"[KB AUTOPILOT] Search API failed: {search_res.get('error')}. Falling back to listing all articles.")
            search_res = {"articles": []}
            
        articles = search_res.get("articles", [])

        # Fallback: if search returned nothing, list all articles and let AI pick the best one
        if not articles:
            logger.info("[KB AUTOPILOT] Search returned 0 results. Falling back to listing all articles.")
            list_res = await self.zoho.get_articles(limit=50)
            articles = list_res.get("articles", [])

        if not articles:
            return {"success": True, "resolved": False, "confidence": 0.0, "reply_content": ""}

        # 3. If multiple articles, let AI pick the most relevant one; otherwise use the only one
        best_article_id = None
        if len(articles) == 1:
            best_article_id = articles[0].get("id")
        else:
            # Build a summary of available articles for the AI to choose from
            article_summaries = []
            for i, a in enumerate(articles[:10]):  # Limit to top 10 to save tokens
                title = a.get("title") or a.get("question") or f"Article {i+1}"
                summary = a.get("summary") or a.get("question") or ""
                article_summaries.append(f"[{i}] ID={a.get('id')} | Title: {title} | Summary: {summary[:200]}")

            pick_prompt = f"""You are a support ticket routing expert. Given a customer ticket, pick the single most relevant Knowledge Base article from the list below.

TICKET SUBJECT: {subject}
TICKET DESCRIPTION: {description[:500]}

AVAILABLE ARTICLES:
{chr(10).join(article_summaries)}

Respond with ONLY the article ID (the number after ID=). If none are relevant, respond with "NONE"."""

            pick_res = await llm_service.chat_completion(
                messages=[{"role": "system", "content": pick_prompt}],
                temperature=0.0
            )
            picked = pick_res.content.strip()
            if picked != "NONE":
                best_article_id = picked
            else:
                return {"success": True, "resolved": False, "confidence": 0.0, "reply_content": ""}

        if not best_article_id:
            return {"success": True, "resolved": False, "confidence": 0.0, "reply_content": ""}

        # 4. Fetch full article content
        article_res = await self.zoho.get_article(best_article_id)
        article_content = article_res.get("article", {}).get("answer", "")

        if not article_content:
             return {"success": True, "resolved": False, "confidence": 0.0, "reply_content": ""}

        # 5. Use LLM to evaluate if the article resolves the ticket and draft a reply
        prompt = f"""
        You are an elite customer support AI. Evaluate if the following Knowledge Base article completely resolves the customer's ticket.
        If it does, draft a friendly, professional reply to the customer using ONLY information from the article.
        If it does not completely resolve the issue, set "resolved" to false.

        TICKET SUBJECT: {subject}
        TICKET DESCRIPTION: {description}

        KB ARTICLE FOUND:
        {article_content}

        OUTPUT FORMAT (JSON):
        {{
            "resolved": true,
            "confidence": 0.95,
            "reply_content": "Drafted reply to the customer (if resolved is true, else empty string)"
        }}
        """

        llm_res = await llm_service.chat_completion(
            messages=[{"role": "system", "content": prompt}],
            temperature=0.1
        )

        try:
            import json
            content = llm_res.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            evaluation = json.loads(content)
            return {"success": True, **evaluation}
        except Exception as e:
            logger.error(f"Failed to parse LLM resolution: {e}")
            return {"success": False, "error": "AI failed to evaluate ticket resolution."}


    async def analyze_knowledge_gaps(self, department_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Analyzed recent unresolved tickets to identify missing KB topics.
        """
        # 1. Fetch recent unresolved tickets
        params = {"status": "Open", "limit": 50}
        if department_id:
            params["departmentId"] = department_id
            
        tickets_res = await self.zoho.get_tickets(limit=50, department_id=department_id)
        tickets = tickets_res.get("tickets", [])
        
        if not tickets:
            return {"success": True, "gaps": [], "message": "No open tickets found for analysis."}

        # 2. Extract themes
        ticket_texts = [f"[{t.get('id')}] {t.get('subject')}" for t in tickets]
        
        prompt = f"""
        Analyze these recent customer support ticket subjects and cluster them into 3-5 recurring "Knowledge Gaps" where a new KB article would reduce ticket volume.
        
        TICKET LIST:
        {chr(10).join(ticket_texts)}
        
        OUTPUT FORMAT (JSON):
        {{
            "gaps": [
                {{
                    "theme": "Theme Name",
                    "reason": "Why this is a gap",
                    "suggested_title": "Proposed Article Title",
                    "ticket_ids": ["id1", "id2"]
                }}
            ]
        }}
        """
        
        llm_res = await llm_service.chat_completion(
            messages=[{"role": "system", "content": prompt}]
        )
        
        try:
            import json
            content = llm_res.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            gaps = json.loads(content)
            return {"success": True, **gaps}
        except Exception as e:
            logger.error(f"Failed to parse Knowledge Gaps: {e}")
            return {"success": False, "error": "AI failed to analyze knowledge gaps."}
