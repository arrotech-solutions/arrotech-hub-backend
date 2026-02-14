"""
Blog router for Arrotech Hub.
Public blog + admin CRUD endpoints.
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from ..database import get_db
from ..models import BlogPostModel, BlogCategory, User
from ..routers.auth_router import get_current_user
from ..config import settings

router = APIRouter(prefix="/api/blog", tags=["blog"])


# ── Pydantic Schemas ─────────────────────────────────────

class BlogPostCreate(BaseModel):
    title: str
    slug: str
    description: str
    content: str
    cover_image: Optional[str] = None
    author_name: Optional[str] = None
    author_avatar: Optional[str] = None
    category_id: Optional[int] = None
    tags: Optional[List[str]] = None
    status: Optional[str] = "draft"
    is_featured: Optional[bool] = False
    read_time: Optional[str] = None


class BlogPostUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    cover_image: Optional[str] = None
    author_name: Optional[str] = None
    author_avatar: Optional[str] = None
    category_id: Optional[int] = None
    tags: Optional[List[str]] = None
    status: Optional[str] = None
    is_featured: Optional[bool] = None
    read_time: Optional[str] = None


# ── Helper ────────────────────────────────────────────────

def _serialize_post(post: BlogPostModel) -> dict:
    return {
        "id": post.id,
        "slug": post.slug,
        "title": post.title,
        "description": post.description,
        "content": post.content,
        "cover_image": post.cover_image,
        "author_name": post.author_name,
        "author_avatar": post.author_avatar,
        "category_id": post.category_id,
        "category": post.category.name if post.category else None,
        "tags": post.tags or [],
        "status": post.status or "draft",
        "is_featured": post.is_featured or False,
        "read_time": post.read_time,
        "views_count": post.views_count or 0,
        "published_at": post.published_at.isoformat() if post.published_at else None,
        "created_at": post.created_at.isoformat() if post.created_at else None,
        "updated_at": post.updated_at.isoformat() if post.updated_at else None,
    }


# ── Public Endpoints ──────────────────────────────────────

@router.get("/posts")
async def list_posts(
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=50),
    category: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List blog posts (public: only published, admin: all)."""
    query = select(BlogPostModel).order_by(BlogPostModel.created_at.desc())

    # Default to published only for public access
    if not status_filter:
        query = query.where(BlogPostModel.status == "published")
    else:
        query = query.where(BlogPostModel.status == status_filter)

    if category:
        query = query.join(BlogCategory).where(BlogCategory.slug == category)

    if search:
        search_term = f"%{search}%"
        from sqlalchemy import or_
        query = query.where(
            or_(
                BlogPostModel.title.ilike(search_term),
                BlogPostModel.description.ilike(search_term),
            )
        )

    # Count total
    count_query = select(sa_func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Paginate
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    posts = result.scalars().all()

    import math
    return {
        "success": True,
        "posts": [_serialize_post(p) for p in posts],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, math.ceil(total / per_page)),
    }


@router.get("/posts/featured")
async def list_featured_posts(
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    """Get featured blog posts."""
    result = await db.execute(
        select(BlogPostModel)
        .where(BlogPostModel.is_featured == True, BlogPostModel.status == "published")
        .order_by(BlogPostModel.published_at.desc())
        .limit(limit)
    )
    posts = result.scalars().all()
    return {"success": True, "posts": [_serialize_post(p) for p in posts]}


@router.get("/posts/{slug}")
async def get_post(slug: str, db: AsyncSession = Depends(get_db)):
    """Get a single blog post by slug."""
    result = await db.execute(
        select(BlogPostModel).where(BlogPostModel.slug == slug)
    )
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Increment views
    post.views_count = (post.views_count or 0) + 1
    await db.commit()

    return {"success": True, "post": _serialize_post(post)}


@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db)):
    """List all blog categories."""
    result = await db.execute(
        select(BlogCategory).order_by(BlogCategory.name)
    )
    categories = result.scalars().all()
    return {
        "success": True,
        "categories": [
            {
                "id": c.id,
                "name": c.name,
                "slug": c.slug,
                "description": c.description,
                "color": c.color,
                "post_count": c.post_count or 0,
            }
            for c in categories
        ],
    }


# ── Admin / Auth Endpoints ────────────────────────────────

@router.post("/posts")
async def create_post(
    data: BlogPostCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new blog post."""
    post = BlogPostModel(
        slug=data.slug,
        title=data.title,
        description=data.description,
        content=data.content,
        cover_image=data.cover_image,
        author_name=data.author_name or current_user.name,
        author_avatar=data.author_avatar,
        category_id=data.category_id,
        tags=data.tags,
        status=data.status or "draft",
        is_featured=data.is_featured or False,
        read_time=data.read_time,
        published_at=datetime.utcnow() if data.status == "published" else None,
    )
    db.add(post)
    await db.commit()
    await db.refresh(post)

    return {"success": True, "message": "Post created", "post": _serialize_post(post)}


@router.put("/posts/{post_id}")
async def update_post(
    post_id: int,
    data: BlogPostUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a blog post."""
    result = await db.execute(select(BlogPostModel).where(BlogPostModel.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    update_data = data.model_dump(exclude_unset=True)

    # If publishing for the first time, set published_at
    if update_data.get("status") == "published" and not post.published_at:
        update_data["published_at"] = datetime.utcnow()

    for key, value in update_data.items():
        setattr(post, key, value)

    await db.commit()
    await db.refresh(post)

    return {"success": True, "message": "Post updated", "post": _serialize_post(post)}


@router.delete("/posts/{post_id}")
async def delete_post(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a blog post."""
    result = await db.execute(select(BlogPostModel).where(BlogPostModel.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    await db.delete(post)
    await db.commit()

    return {"success": True, "message": "Post deleted"}


@router.post("/seed")
async def seed_blog_data(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Seed initial blog categories and sample posts."""
    # Check if categories already exist
    existing = await db.execute(select(sa_func.count(BlogCategory.id)))
    if (existing.scalar() or 0) > 0:
        return {"success": True, "message": "Blog data already seeded"}

    categories = [
        BlogCategory(name="Engineering", slug="engineering", description="Technical deep-dives and engineering insights", color="#6366F1"),
        BlogCategory(name="Product", slug="product", description="Product updates and roadmap", color="#8B5CF6"),
        BlogCategory(name="Company", slug="company", description="Company news and culture", color="#EC4899"),
        BlogCategory(name="Tutorials", slug="tutorials", description="Step-by-step guides and tutorials", color="#14B8A6"),
    ]
    db.add_all(categories)
    await db.commit()

    return {"success": True, "message": "Blog categories seeded", "categories_created": len(categories)}
