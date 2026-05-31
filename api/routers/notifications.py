from fastapi import APIRouter, Depends, HTTPException
from core.config import supabase
from services.auth_service import get_current_user
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter()

class Notification(BaseModel):
    id: int
    user_id: int
    title: str
    content: str
    link: Optional[str] = None
    is_read: bool
    created_at: str

@router.get("/unread-count")
async def get_unread_count(user: dict = Depends(get_current_user)):
    user_id = user.get("user_id")
    # Sử dụng count='exact' để chỉ lấy số lượng, không lấy dữ liệu bản ghi
    res = supabase.table("notifications").select("id", count="exact").eq("user_id", user_id).eq("is_read", False).execute()
    return {"count": res.count if res.count is not None else 0}

@router.get("")
async def get_my_notifications(user: dict = Depends(get_current_user)):
    user_id = user.get("user_id")
    res = supabase.table("notifications").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(20).execute()
    return res.data

@router.post("/{notif_id}/read")
async def mark_as_read(notif_id: int, user: dict = Depends(get_current_user)):
    curr_user_id = user.get("user_id")
    print(f">>> DEBUG: Marking notif {notif_id} as read for user {curr_user_id}")
    res = supabase.table("notifications").update({"is_read": True}).eq("id", notif_id).eq("user_id", curr_user_id).execute()
    print(f">>> DEBUG: Result: {res.data}")
    return {"success": True}

@router.post("/read-all")
async def mark_all_as_read(user: dict = Depends(get_current_user)):
    curr_user_id = user.get("user_id")
    print(f">>> DEBUG: Marking all read for user {curr_user_id}")
    res = supabase.table("notifications").update({"is_read": True}).eq("user_id", curr_user_id).execute()
    return {"success": True}

# Hàm helper để tạo thông báo từ phía server
def create_notification(user_id: int, title: str, content: str, link: str = None):
    try:
        data = {
            "user_id": user_id,
            "title": title,
            "content": content,
            "link": link,
            "is_read": False
        }
        supabase.table("notifications").insert(data).execute()
    except Exception as e:
        print(f">>> ERROR creating notification: {e}")
