from fastapi import APIRouter, Depends, HTTPException
from core.config import supabase
from services.auth_service import get_current_user
from pydantic import BaseModel
from typing import List, Optional
import firebase_admin
from firebase_admin import messaging

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
    res = supabase.table("notifications").select("id", count="exact").eq("user_id", user_id).eq("is_read", False).execute()
    return {"count": res.count if res.count is not None else 0}

@router.get("")
async def get_my_notifications(user: dict = Depends(get_current_user)):
    user_id = user.get("user_id")
    res = supabase.table("notifications").select("*, sender:created_by(full_name)").eq("user_id", user_id).order("created_at", desc=True).limit(20).execute()
    result = []
    for n in res.data:
        sender_info = n.pop("sender", None)
        n["sender_name"] = sender_info.get("full_name") if sender_info else "Hệ thống"
        result.append(n)
    return result

@router.post("/{notif_id}/read")
async def mark_as_read(notif_id: int, user: dict = Depends(get_current_user)):
    curr_user_id = user.get("user_id")
    res = supabase.table("notifications").update({"is_read": True}).eq("id", notif_id).eq("user_id", curr_user_id).execute()
    return {"success": True}

@router.post("/read-all")
async def mark_all_as_read(user: dict = Depends(get_current_user)):
    curr_user_id = user.get("user_id")
    res = supabase.table("notifications").update({"is_read": True}).eq("user_id", curr_user_id).execute()
    return {"success": True}

# Hàm helper để tạo thông báo từ phía server
def create_notification(user_id: int, title: str, content: str, link: str = None, created_by: int = None):
    try:
        data = {
            "user_id": user_id,
            "title": title,
            "content": content,
            "link": link,
            "is_read": False,
            "created_by": created_by
        }
        res = supabase.table("notifications").insert(data).execute()
        
        # Gửi Push Notification qua Firebase
        if res.data:
            user_res = supabase.table("users").select("fcm_token").eq("id", user_id).execute()
            if user_res.data and len(user_res.data) > 0:
                fcm_token = user_res.data[0].get("fcm_token")
                if fcm_token:
                    try:
                        message = messaging.Message(
                            notification=messaging.Notification(
                                title=title,
                                body=content,
                            ),
                            data={"link": link or ""},
                            token=fcm_token,
                        )
                        messaging.send(message)
                        print(f">>> Sent FCM to user {user_id}")
                    except Exception as e:
                        print(f">>> ERROR sending FCM to user {user_id}: {e}")

    except Exception as e:
        print(f">>> ERROR creating notification: {e}")

class FcmTokenRequest(BaseModel):
    fcm_token: str

@router.post("/fcm-token")
async def update_fcm_token(req: FcmTokenRequest, user: dict = Depends(get_current_user)):
    user_id = user.get("user_id")
    supabase.table("users").update({"fcm_token": req.fcm_token}).eq("id", user_id).execute()
    return {"success": True, "message": "Đã cập nhật FCM Token"}

class AdminNotificationRequest(BaseModel):
    target_user_ids: List[int] # Contains 0 if sending to all users
    title: str
    content: str
    link: Optional[str] = None

@router.post("/admin/send")
async def send_admin_notification(req: AdminNotificationRequest, user: dict = Depends(get_current_user)):
    created_by = user.get("user_id")
    if 0 in req.target_user_ids:
        # Send to all users except deleted ones
        users_res = supabase.table("users").select("id, username").execute()
        for u in users_res.data:
            if "_deleted_" not in u.get("username", ""):
                create_notification(u["id"], req.title, req.content, req.link, created_by)
    else:
        # Send to specific users
        for uid in req.target_user_ids:
            create_notification(uid, req.title, req.content, req.link, created_by)
        
    return {"success": True, "message": "Đã phát hành thông báo thành công"}

@router.delete("/all")
async def delete_all_notifications(user: dict = Depends(get_current_user)):
    user_id = user.get("user_id")
    res = supabase.table("notifications").delete().eq("user_id", user_id).execute()
    return {"success": True, "message": "Đã xóa toàn bộ thông báo"}
