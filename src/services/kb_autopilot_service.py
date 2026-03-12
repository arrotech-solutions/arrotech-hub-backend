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
        Analyzes a ticket and its resolution to draft a Knowledge Base article,
        then automatically creates it as a Draft in Zoho Desk KB.
        """
        # 1. Fetch ticket details
        ticket_res = await self.zoho._desk_request("GET", f"/desk/api/v1/tickets/{ticket_id}")
        if not ticket_res or "id" not in ticket_res:
            return {"success": False, "error": f"Ticket {ticket_id} not found."}

        department_id = ticket_res.get("departmentId")

        # 2. Fetch conversation (replies/threads)
        threads_res = await self.zoho._desk_request("GET", f"/desk/api/v1/tickets/{ticket_id}/threads")
        threads = []
        if isinstance(threads_res, dict):
            threads = threads_res.get("data", [])
        elif isinstance(threads_res, list):
            threads = threads_res

        # 3. Construct context for LLM
        context = f"Subject: {ticket_res.get('subject')}\n"
        context += f"Description: {ticket_res.get('description')}\n\n"
        context += "Conversation History:\n"
        
        for t in threads:
            if not isinstance(t, dict):
                continue
            sender = t.get("from", "Unknown")
            content = t.get("content", "")
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
        except Exception as e:
            logger.error(f"Failed to parse LLM draft: {e}")
            return {"success": False, "error": "AI failed to generate a valid JSON draft."}

        # 5. Find a KB category to put the article in
        category_id = await self._find_or_get_default_category(draft.get("category_name", "General"))

        if not category_id:
            logger.warning("[KB AUTOPILOT] No KB category found. Returning draft without creating article in Zoho.")
            return {"success": True, "draft": draft, "zoho_article": None, 
                    "message": "Draft generated but could not be saved to Zoho KB — no categories found. Please create a KB category in Zoho Desk first."}

        # 6. Create the article as a Draft in Zoho Desk KB
        article_payload = {
            "title": draft.get("title", "Untitled Article"),
            "answer": draft.get("content", ""),
            "status": "Draft",
            "categoryId": int(category_id),
            "permission": "ALL",
        }

        logger.info(f"[KB AUTOPILOT] Creating draft article in Zoho KB: {draft.get('title')}")
        logger.info(f"[KB AUTOPILOT] Article payload: {article_payload}")
        create_res = await self.zoho._desk_request("POST", "/desk/api/v1/articles", json_data=article_payload)
        
        if isinstance(create_res, dict) and create_res.get("id"):
            logger.info(f"[KB AUTOPILOT] Draft article created in Zoho KB with ID: {create_res['id']}")
            return {
                "success": True, 
                "draft": draft,
                "zoho_article": {
                    "id": create_res["id"],
                    "title": create_res.get("title", draft.get("title")),
                    "status": "Draft",
                    "url": create_res.get("webUrl", "")
                },
                "message": f"Draft article '{draft.get('title')}' created in Zoho Desk KB."
            }
        else:
            logger.warning(f"[KB AUTOPILOT] Failed to create article in Zoho KB: {create_res}")
            return {
                "success": True, 
                "draft": draft,
                "zoho_article": None,
                "message": f"Draft generated but failed to save to Zoho KB: {create_res}"
            }

    async def _find_or_get_default_category(self, suggested_name: str) -> Optional[str]:
        """
        Find a KB section ID to use for creating articles.
        Zoho articles need a section (child) ID, NOT a root category ID.
        Flow: list root categories -> get category tree -> find/create a section.
        """
        try:
            # Step 1: List root categories
            categories_res = await self.zoho._desk_request("GET", "/desk/api/v1/kbRootCategories")
            
            categories = []
            if isinstance(categories_res, dict) and "data" in categories_res:
                categories = categories_res["data"]
            elif isinstance(categories_res, list):
                categories = categories_res

            if not categories:
                logger.warning("[KB AUTOPILOT] No KB root categories found.")
                return None

            # Step 2: Find the best matching root category by name
            target_root = None
            suggested_lower = suggested_name.lower()
            
            for cat in categories:
                if not isinstance(cat, dict):
                    continue
                cat_name = cat.get("name", "")
                translations = cat.get("translations", [])
                translation_names = [t.get("name", "") for t in translations if isinstance(t, dict)]
                all_names = [cat_name] + translation_names
                
                for name in all_names:
                    if name and suggested_lower in name.lower():
                        target_root = cat
                        logger.info(f"[KB AUTOPILOT] Matched root category: {name} (ID: {cat.get('id')})")
                        break
                if target_root:
                    break

            # Fallback: use the first root category
            if not target_root:
                target_root = categories[0]
                logger.info(f"[KB AUTOPILOT] Using default root category: {target_root.get('name')} (ID: {target_root.get('id')})")

            root_id = target_root.get("id")
            if not root_id:
                return None

            # Step 3: Get the category tree to find sections (children)
            tree_res = await self.zoho._desk_request("GET", f"/desk/api/v1/kbRootCategories/{root_id}/categoryTree")
            
            if isinstance(tree_res, dict):
                tree_id = tree_res.get("id")
                tree_name = tree_res.get("name")
                children = tree_res.get("children", [])
                logger.info(f"[KB AUTOPILOT] Category tree: id={tree_id}, name={tree_name}, root_id={root_id}, children_count={len(children)}")
                
                if children:
                    section = children[0]
                    section_id = section.get("id")
                    section_name = section.get("name", "Unknown")
                    section_root = section.get("rootCategoryId")
                    section_parent = section.get("parentCategoryId")
                    logger.info(f"[KB AUTOPILOT] Section: id={section_id}, name={section_name}, rootCategoryId={section_root}, parentCategoryId={section_parent}")
                    
                    # Check if the section has its own children (sub-sections) — articles may need the deepest level
                    sub_children = section.get("children", [])
                    if sub_children:
                        leaf = sub_children[0]
                        leaf_id = leaf.get("id")
                        leaf_name = leaf.get("name", "Unknown")
                        logger.info(f"[KB AUTOPILOT] Using leaf sub-section: {leaf_name} (ID: {leaf_id})")
                        return leaf_id
                    
                    return section_id
            else:
                children = []
                logger.warning(f"[KB AUTOPILOT] Category tree response not a dict: {tree_res}")

            # Step 4: No sections exist — create one
            logger.info(f"[KB AUTOPILOT] No sections found under root category {root_id}. Creating 'General' section...")
            section_data = {
                "name": "General",
                "description": "Auto-created section for KB articles",
                "parentCategoryId": int(root_id),
                "status": "SHOW_IN_HELPCENTER"
            }
            create_section_res = await self.zoho._desk_request(
                "POST", "/desk/api/v1/kbSections", json_data=section_data
            )
            
            if isinstance(create_section_res, dict) and create_section_res.get("id"):
                section_id = create_section_res["id"]
                logger.info(f"[KB AUTOPILOT] Created section 'General' (ID: {section_id})")
                return section_id
            else:
                logger.warning(f"[KB AUTOPILOT] Failed to create section: {create_section_res}")
                # Last resort: try using the root category ID directly
                return root_id

        except Exception as e:
            logger.error(f"[KB AUTOPILOT] Error finding KB category: {e}")
            return None

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
